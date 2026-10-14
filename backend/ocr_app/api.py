"""Local HTTP shell; model loading belongs to the injected runtime."""
from contextlib import asynccontextmanager, suppress
from ipaddress import ip_address
from pathlib import Path
from tempfile import TemporaryFile
from typing import Literal
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .task_store import TaskError


class ModelStates(BaseModel):
    model_config = ConfigDict(extra='forbid')
    glm_ocr: Literal['unloaded', 'loading', 'warming', 'ready', 'failed', 'stopping']
    paddleocr_vl: Literal['unloaded', 'loading', 'warming', 'ready', 'failed', 'stopping']


class RuntimeSnapshot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    configured_mode: Literal['dual_resident', 'single_resident']
    effective_mode: Literal['dual_resident', 'single_resident', 'ocr_unavailable'] | None
    state: Literal['starting', 'ready', 'degraded', 'stopping']
    models: ModelStates
    reason_code: Literal['RESOURCE_LIMIT', 'MODEL_LOAD_FAILED', 'MODEL_WARMUP_FAILED',
                         'MODEL_PROCESS_EXITED', 'SUPERVISION_FAILED'] | None


def create_app(runtime, static_dir: Path, storage_dir: Path, business=None, logger=None) -> FastAPI:
    storage_ready = False
    startup_failed = False

    @asynccontextmanager
    async def lifespan(app):
        nonlocal storage_ready, startup_failed
        try:
            storage_dir.mkdir(parents=True, exist_ok=True)
            with TemporaryFile(dir=storage_dir) as probe:
                probe.write(b'health')
                probe.flush()
            storage_ready = True
        except OSError as error:
            storage_ready = False
            if logger:
                logger.exception('storage_failed', error)
        try:
            try:
                runtime.start()
                if business:
                    business.watch(runtime)
            except Exception as error:
                startup_failed = True
                if logger:
                    logger.exception('runtime_start_failed', error)
            yield
        finally:
            try:
                runtime.close()
            except Exception as error:
                if logger:
                    logger.exception('runtime_close_failed', error)
            if business:
                business.close()

    app = FastAPI(version='1.25.0', lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1'],
                       www_redirect=False)

    @app.exception_handler(TaskError)
    async def task_error(request, error):
        request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
        error_id = logger.exception('request_failed', error, request_id=request_id, error_code=error.code) if logger else str(uuid.uuid4())
        payload = dict(code=error.code, message=error.message, error_id=error_id, request_id=request_id)
        if getattr(error, 'details', None) is not None:
            payload['details'] = error.details
        return JSONResponse(payload, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Pydantic error.details can include submitted values. Never echo those.
        return await task_error(request, TaskError('INVALID_REQUEST', '请求参数无效，请刷新后重试', 422))

    @app.middleware('http')
    async def loopback_only(request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())
        begin = time.monotonic()
        try:
            allowed = bool(request.client and ip_address(request.client.host).is_loopback)
        except ValueError:
            allowed = False
        if not allowed:
            return PlainTextResponse('Forbidden', status_code=403)
        try:
            response = await call_next(request)
        except Exception as error:
            error_id = logger.exception('request_failed', error, request_id=request.state.request_id) if logger else str(uuid.uuid4())
            response = JSONResponse(dict(code='INTERNAL_ERROR', message='处理失败，请保存错误编号和诊断记录',
                                         error_id=error_id, request_id=request.state.request_id), status_code=500)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        if logger and not request.url.path.endswith('/health'):
            logger.event('request_completed', request_id=request.state.request_id,
                         http_status=response.status_code, duration_seconds=time.monotonic()-begin)
        return response

    def health():
        snapshot = None
        worker_ready = False
        if not startup_failed:
            try:
                snapshot = RuntimeSnapshot.model_validate(runtime.snapshot()).model_dump()
                worker_ready = bool(runtime.is_alive())
            except Exception:
                # Invalid/internal state must not become a public exception or path leak.
                snapshot = None
        response = {'status': 'degraded', 'version': '1.25.0', 'queue_depth': None,
                    'components': {'db': 'down', 'worker': 'ok' if worker_ready else 'down',
                                   'storage': 'ok' if storage_ready else 'down'}}
        if snapshot is not None:
            response['runtime'] = snapshot
        if business:
            try:
                response['queue_depth'] = business.store.queue_depth()
                response['components']['db'] = 'ok'
            except Exception as error:
                if logger:
                    logger.exception('storage_failed', error)
            if all(v == 'ok' for v in response['components'].values()):
                response['status'] = 'ok'
        return response

    @app.get('/health')
    def public_health():
        return {'status': health()['status']}

    if business:
        from .routes import router
        app.include_router(router(business, runtime, health))
    else:
        @app.get('/api/v1/health')
        def unavailable_health():
            raise TaskError('UNAUTHORIZED', '请登录工作台', 401)

    if (static_dir / 'index.html').is_file():
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='frontend')
    else:
        @app.get('/')
        def unbuilt_frontend():
            return PlainTextResponse('Frontend is not built.', status_code=503)

    return app
