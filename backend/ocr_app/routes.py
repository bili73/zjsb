"""Authenticated phase-two routes. Upload parsing is explicitly memory-only."""
import uuid
import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool

from .business import prepare_uploads
from .task_store import TaskError, SUPPORTED, upload_types
from .auth import SESSION_COOKIE, SESSION_SECONDS, same_origin, csrf_for, request_user
from .upload_limits import MAX_FILES, MAX_FILE_BYTES, MAX_BATCH_BYTES


class Version(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: uuid.UUID
    expected_revision: int = Field(ge=0, strict=True)


class WorkbenchLayoutBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layout: list[Annotated[str, Field(strict=True, min_length=1, max_length=64)]] | None = Field(max_length=13)
    expected_revision: int = Field(ge=0, le=9007199254740991, strict=True)


class ReviewBody(Version):
    fields: dict = Field(default_factory=dict)
    absence_reasons: dict = Field(default_factory=dict)
    accepted_issues: list[dict] = Field(default_factory=list)
    confirm_export_disputes: bool = Field(default=False, strict=True)
    confirmed_disputes: list[Annotated[str, Field(pattern=r'^d_[0-9a-f]{64}$')]] = Field(default_factory=list, max_length=10000)
    items: list[dict] = Field(default_factory=list)
    added_items: list[dict] = Field(default_factory=list)
    removed_item_ids: list[str] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    report_summary: dict | None = None
    members: list[dict] = Field(default_factory=list)
    added_members: list[dict] = Field(default_factory=list)
    removed_member_indexes: list[int] = Field(default_factory=list)
    coverage: dict | None = None
    generic: dict | None = None
    tables: list[dict] | None = None
    note: str | None = Field(default=None, max_length=1000)


class DeleteTaskVersion(Version):
    task_id: uuid.UUID


class DeleteBatchBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    versions: list[DeleteTaskVersion] = Field(min_length=1)


class FullPreview(Version):
    page: int = Field(default=1, ge=1)
    reason: str | None = Field(default=None, max_length=1000)
    rendition: Literal['original', 'display'] = 'original'


class RegionOCRBody(Version):
    page: int = Field(ge=1, strict=True)
    field_key: str | None = Field(default=None, min_length=1, max_length=64, pattern=r'^[a-z_]+$')
    bbox: list[Annotated[float, Field(ge=0, le=1, strict=True, allow_inf_nan=False)]] = Field(min_length=4, max_length=4)


class RevealBody(Version):
    fields: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=1000, pattern=r'\S')


class ExportBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    batch_id: uuid.UUID | None = None
    task_ids: list[uuid.UUID] | None = None
    masked: bool = True
    reason: str | None = None
    versions: list[dict] | None = None
    format: Literal['xlsx'] = 'xlsx'


class PersonBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    person_name: str = Field(min_length=1, max_length=80)
    expected_revision: int = Field(ge=0, strict=True)


class FrontendDiagnosticBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    origin: Literal['vue', 'window', 'promise', 'http']
    operation: str = Field(pattern=r'^[a-z_]{1,40}$')
    code: Literal['CLIENT_ERROR', 'NETWORK_ERROR', 'REQUEST_TIMEOUT', 'INVALID_RESPONSE']
    client_error_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,80}$')
    request_id: str | None = Field(default=None, pattern=r'^[a-fA-F0-9-]{36}$')
    line: int | None = Field(default=None, ge=0, le=10000000)
    column: int | None = Field(default=None, ge=0, le=10000000)
    exception_type: str | None = Field(default=None, max_length=40)
    browser_event: str | None = Field(default=None, max_length=40)
    frontend_build: str | None = Field(default=None, pattern=r'^b_[A-Za-z0-9_-]{8,64}$')


async def bounded_json(request):
    import json
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 8192:
            raise TaskError('INVALID_REQUEST', '请求内容过大', 413)
        data.extend(chunk)
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise TaskError('INVALID_REQUEST', '请求内容无效', 422)


async def memory_form(request, *, classification=False):
    media, options = parse_options_header(request.headers.get('content-type', ''))
    boundary = options.get(b'boundary')
    if media != b'multipart/form-data' or not boundary or len(boundary) > 200:
        raise TaskError('INVALID_REQUEST', '请使用文件上传表单', 400)
    files, fields, current, header, ended = [], {}, {}, {}, [False]
    max_files = 1 if classification else MAX_FILES
    max_bytes = MAX_FILE_BYTES if classification else MAX_BATCH_BYTES
    field_limits = {} if classification else dict(doc_type_hint=64, abnormal_only=64, person_name=320, expected_revision=64, file_types=4096)

    def part_begin():
        current.clear()
        current.update(headers={}, body=bytearray())

    def header_field(data, start, end):
        header.setdefault('name', bytearray()).extend(data[start:end])

    def header_value(data, start, end):
        header.setdefault('value', bytearray()).extend(data[start:end])

    def header_end():
        if len(header.get('value', b'')) > 4096:
            raise TaskError('INVALID_REQUEST', '表单头过长', 400)
        current['headers'][bytes(header.get('name', b'')).lower()] = bytes(header.get('value', b''))
        header.clear()

    def data_part(data, start, end):
        if len(current['body']) + end - start > MAX_FILE_BYTES:
            raise TaskError('FILE_TOO_LARGE', '单文件不超过50MB', 413)
        current['body'].extend(data[start:end])

    def part_end():
        _, values = parse_options_header(current['headers'].get(b'content-disposition', b''))
        name = values.get(b'name', b'').decode('utf-8', errors='strict')
        if name == 'files' and b'filename' in values:
            if len(files) >= max_files:
                raise TaskError('FILE_TOO_LARGE', '每批最多100个文件', 413)
            if sum(len(data) for data, _ in files) + len(current['body']) > max_bytes:
                raise TaskError('FILE_TOO_LARGE', '单次上传总大小不超过500MB', 413)
            files.append((bytes(current['body']), values[b'filename'].decode('utf-8', errors='strict')))
        elif name in field_limits and len(current['body']) <= field_limits[name] and name not in fields:
            fields[name] = bytes(current['body']).decode('utf-8')
        else:
            raise TaskError('INVALID_REQUEST', '表单字段无效或重复', 400)

    parser = MultipartParser(boundary, dict(on_part_begin=part_begin, on_header_field=header_field,
        on_header_value=header_value, on_header_end=header_end, on_part_data=data_part,
        on_part_end=part_end, on_end=lambda: ended.__setitem__(0, True)))
    size = 0
    try:
        async for chunk in request.stream():
            size += len(chunk)
            # Framing is bounded separately from the aggregate file payload.
            if size > max_bytes + (max_files + 5) * 8192:
                raise TaskError('FILE_TOO_LARGE', '单次上传总大小不超过500MB', 413)
            parser.write(chunk)
        parser.finalize()
    except TaskError:
        raise
    except Exception as error:
        raise TaskError('INVALID_REQUEST', '上传表单不完整或编码无效', 400) from error
    if not ended[0] or not files:
        raise TaskError('INVALID_REQUEST', '上传表单不完整', 400)
    if classification:
        return files, fields
    if 'file_types' in fields:
        if 'doc_type_hint' in fields:
            raise TaskError('INVALID_REQUEST', '不能同时提交统一类型与逐文件类型', 422)
        try:
            kinds = json.loads(fields['file_types'])
        except ValueError as error:
            raise TaskError('INVALID_REQUEST', '逐文件类型须为JSON数组', 422) from error
        if not isinstance(kinds, list):
            raise TaskError('INVALID_REQUEST', '逐文件类型须为JSON数组', 422)
        fields['file_types'] = upload_types(kinds, len(files))
    elif fields.get('doc_type_hint') not in SUPPORTED:
        raise TaskError('UNSUPPORTED_DOC_TYPE', '材料类型未受支持，请从材料目录选择', 422)
    if fields.get('abnormal_only', 'false').lower() not in {'true', 'false'}:
        raise TaskError('INVALID_REQUEST', '异常项目开关无效', 400)
    return files, fields


def router(business, runtime, health):
    def principal(request: Request):
        return request_user(business.accounts, request)

    def operator(user=Depends(principal)):
        if user['role'] not in {'operator', 'admin'}:
            raise TaskError('FORBIDDEN_REVEAL', '当前账号无此操作权限', 403)
        return user

    def administrator(user=Depends(principal)):
        if user['role'] != 'admin':
            raise TaskError('FORBIDDEN', '只有管理员可以修改管理设置', 403)
        return user

    # New business routes inherit authentication even without an endpoint dependency.
    routes = APIRouter(dependencies=[Depends(principal)])
    public = APIRouter(prefix='/api/v1')

    def authorization(request, user):
        def authorize(connection):
            current = request_user(business.accounts, request, connection=connection)
            if current['user_id'] != user['user_id']:
                raise TaskError('UNAUTHORIZED', '登录状态已变化，请重新登录', 401)
            if current['role'] != user['role']:
                raise TaskError('FORBIDDEN', '账号权限已变化，请刷新工作台后再试', 403)
            operator(current)
        return authorize

    def diagnostics(request):
        service = request.app.state.diagnostics
        if service is None:
            raise TaskError('DIAGNOSTICS_UNAVAILABLE', '诊断服务未配置', 503)
        return service

    async def upload_slot(request: Request, user=Depends(operator)):
        request.state.queue_wait = None
        async with request.app.state.upload_admission.enter(user['user_id']) as waited:
            request.state.queue_wait = waited
            # Waiting must not preserve an account/session that has since been revoked.
            await run_in_threadpool(recheck_admitted, request, user)
            yield

    async def export_slot(request: Request, user=Depends(principal)):
        request.state.queue_wait = None
        async with request.app.state.export_admission.enter(user['user_id']) as waited:
            request.state.queue_wait = waited
            await run_in_threadpool(recheck_admitted, request, user)
            yield

    def recheck_admitted(request, user):
        with business.engine.connect() as connection:
            authorization(request, user)(connection)

    def recheck_diagnostic_user(request, user, *, admin=True):
        with business.engine.connect() as connection:
            return business.accounts._acting_user(connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=admin)

    def diagnostic_filters(
        level: Literal['ERROR', 'CRITICAL'] | None = None,
        date_from: date | None = None, date_to: date | None = None,
        error_id: str | None = Query(default=None, pattern=r'^(?:e_[a-f0-9]{32}|l_[a-f0-9]{32}|[a-fA-F0-9-]{36})$'),
        task_id: uuid.UUID | None = None,
    ):
        return dict(level=level, date_from=date_from.isoformat() if date_from else None,
                    date_to=date_to.isoformat() if date_to else None, error_id=error_id, task_id=str(task_id) if task_id else None)

    @routes.get('/admin/diagnostics/status')
    def diagnostic_status(request: Request, user=Depends(administrator)):
        value = diagnostics(request).status()
        recheck_diagnostic_user(request, user)
        return value

    @routes.get('/admin/diagnostics/events')
    def diagnostic_events(request: Request, filters=Depends(diagnostic_filters), user=Depends(administrator),
                          cursor: str | None = Query(default=None, max_length=160), limit: int = Query(default=50, ge=1, le=100)):
        value = diagnostics(request).query(cursor=cursor, limit=limit, **filters)
        recheck_diagnostic_user(request, user)
        return value

    @routes.get('/admin/diagnostics/bundle')
    def diagnostic_bundle(request: Request, filters=Depends(diagnostic_filters), user=Depends(administrator)):
        data, metadata = diagnostics(request).bundle(**filters)
        recheck_diagnostic_user(request, user)
        return Response(data, media_type='application/zip', headers={
            'Content-Disposition': 'attachment; filename="diagnostics.zip"',
            'X-Diagnostics-Truncated': 'true' if metadata['truncated'] else 'false',
            'X-Diagnostics-Incomplete': 'true' if metadata['incomplete'] else 'false'})

    @routes.post('/diagnostics/frontend', status_code=202)
    async def diagnostic_frontend(request: Request, user=Depends(principal)):
        service = diagnostics(request)
        service.admit_report(user['user_id'])
        raw = await bounded_json(request)
        try:
            body = FrontendDiagnosticBody.model_validate(raw)
            from .diagnostics import ENUMS
            if body.operation not in ENUMS['operation']:
                raise ValueError()
            if body.exception_type is not None and body.exception_type not in ENUMS['frontend_exception_type']:
                raise ValueError()
            if body.browser_event is not None and body.browser_event not in ENUMS['browser_event']:
                raise ValueError()
        except ValueError:
            raise TaskError('INVALID_REQUEST', '诊断数据格式无效', 422) from None
        def record_report():
            # Recheck after reading the body and entering the pool; attribution is server-owned.
            recheck_diagnostic_user(request, user, admin=False)
            service.logger.event('frontend_error', origin=body.origin, operation=body.operation,
                                 error_code=body.code, actor_id=user['user_id'], client_error_id=body.client_error_id,
                                 request_id=body.request_id, frontend_line=body.line, frontend_column=body.column,
                                 frontend_exception_type=body.exception_type, browser_event=body.browser_event,
                                 frontend_build=body.frontend_build)
            if not service.logger.available:
                raise TaskError('DIAGNOSTICS_UNAVAILABLE', '诊断记录暂时无法写入，请下载本页诊断信息', 503)
        await run_in_threadpool(record_report)
        return {'accepted': True}

    @routes.get('/health')
    def full_health():
        return health()

    @routes.get('/auth/me')
    def me(request: Request, user=Depends(principal)):
        payload=dict(user, permissions=['rerun', 'review', 'reveal', 'export'] if user['role'] != 'viewer' else [])
        if request.state.csrf_token:
            payload['csrf_token']=request.state.csrf_token
        return payload

    @routes.get('/auth/me/workbench')
    def workbench_layout(request: Request, user=Depends(principal)):
        from .workbench_preferences import load_preferences
        with business.engine.connect() as connection:
            business.accounts._acting_user(connection, user['user_id'], request.cookies.get(SESSION_COOKIE))
            return load_preferences(connection, user['user_id'])

    @routes.put('/auth/me/workbench')
    def update_workbench_layout(body: WorkbenchLayoutBody, request: Request, user=Depends(principal)):
        from .workbench_preferences import save_layout, load_default
        if body.layout is not None and (len(set(body.layout)) != len(body.layout)
                                        or not set(body.layout) <= SUPPORTED):
            raise TaskError('INVALID_REQUEST', '布局包含重复或不支持的材料类型', 422)
        with business.accounts.transaction() as connection:
            # Personal presentation preferences are writable by all named roles.
            # Recheck the session inside the transaction, including revocation.
            business.accounts._acting_user(connection, user['user_id'], request.cookies.get(SESSION_COOKIE))
            return dict(save_layout(connection, user['user_id'], body.layout, body.expected_revision),
                        defaults=load_default(connection))

    @routes.put('/admin/workbench-default')
    def update_workbench_default(body: WorkbenchLayoutBody, request: Request, user=Depends(administrator)):
        from .workbench_preferences import save_default, load_default
        if body.layout is not None and (len(set(body.layout)) != len(body.layout)
                                        or not set(body.layout) <= SUPPORTED):
            raise TaskError('INVALID_REQUEST', '布局包含重复或不支持的材料类型', 422)
        with business.accounts.transaction() as connection:
            business.accounts._acting_user(connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=True)
            previous = load_default(connection)
            result = save_default(connection, body.layout, body.expected_revision)
            if previous != result:
                business.store._audit(connection, 'workbench_default_changed', user['user_id'],
                                      old_layout=previous['layout'], layout=result['layout'], revision=result['revision'])
            return result

    @public.post('/auth/login')
    async def login(request: Request):
        same_origin(request)
        body=await bounded_json(request)
        if (not isinstance(body,dict) or set(body)!={'username','password'} or
                not isinstance(body['username'],str) or not 1<=len(body['username'])<=64 or
                not isinstance(body['password'],str) or not 1<=len(body['password'])<=128):
            raise TaskError('INVALID_REQUEST', '登录请求无效', 422)
        from starlette.concurrency import run_in_threadpool
        from .audit import CONTEXT
        context = CONTEXT.get()
        if context is not None:
            context['claimed_username'] = body['username']
        token=await run_in_threadpool(business.accounts.login,body['username'],body['password'],
                                     request.client.host,request.cookies.get(SESSION_COOKIE))
        user=business.accounts.session(token)
        if user is None:
            raise TaskError('UNAUTHORIZED', '账号状态已变化，请重新登录', 401)
        response=JSONResponse(dict(user,csrf_token=csrf_for(token),
                                  permissions=['rerun','review','reveal','export'] if user['role']!='viewer' else []))
        response.set_cookie(SESSION_COOKIE,token,max_age=SESSION_SECONDS,httponly=True,
                            secure=request.url.scheme=='https',samesite='strict',path='/')
        return response

    @routes.post('/auth/logout',status_code=204)
    def logout(request: Request, user=Depends(principal)):
        business.accounts.logout(request.cookies.get(SESSION_COOKIE))
        response=Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE,httponly=True,secure=request.url.scheme=='https',samesite='strict',path='/')
        return response

    @routes.get('/admin/users')
    def users(user=Depends(administrator)):
        return dict(items=business.accounts.users())

    def audit_service():
        from .audit import AuditService
        return AuditService(business.engine, business.storage)

    def audit_filters(date_from: date | None = None, date_to: date | None = None,
                      actor: str | None = Query(default=None, max_length=100),
                      event: str | None = Query(default=None, max_length=100),
                      outcome: Literal['success', 'failure', 'requested', 'legacy'] | None = None,
                      batch_id: uuid.UUID | None = None):
        return dict(date_from=date_from.isoformat() if date_from else None,
                    date_to=date_to.isoformat() if date_to else None, actor=actor, event=event, outcome=outcome,
                    batch_id=str(batch_id) if batch_id else None)

    @routes.get('/admin/audit/options')
    def audit_options(request: Request, user=Depends(administrator)):
        result = audit_service().options()
        recheck_diagnostic_user(request, user)
        return result

    @routes.get('/admin/audit/events')
    def audit_events(request: Request, user=Depends(administrator), filters=Depends(audit_filters),
                     cursor: str | None = Query(default=None, max_length=200), limit: int = Query(default=50, ge=1, le=100),
                     page: int | None = Query(default=None, ge=1, le=2147483647),
                     page_size: int | None = Query(default=None, ge=1, le=100)):
        if (page is not None or page_size is not None) and ('cursor' in request.query_params or 'limit' in request.query_params):
            raise TaskError('AUDIT_FILTER_INVALID', '页码分页不能与游标分页同时使用', 422)
        result = audit_service().query(cursor=cursor, limit=limit, page=page, page_size=page_size, **filters)
        recheck_diagnostic_user(request, user)
        return result

    @routes.get('/admin/audit/events/{event_id}')
    def audit_detail(event_id: uuid.UUID, request: Request, user=Depends(administrator)):
        result = audit_service().detail(str(event_id))
        recheck_diagnostic_user(request, user)
        return result

    @routes.get('/admin/audit/export')
    def audit_export(request: Request, user=Depends(administrator), filters=Depends(audit_filters), slot=Depends(export_slot)):
        data, count = audit_service().workbook(**filters)
        with business.store.transaction() as connection:
            business.accounts._acting_user(connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=True)
            business.store._audit(connection, 'audit_export', user['user_id'], records=count)
        return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="operation-audit.xlsx"'})

    @routes.post('/admin/users', status_code=201)
    async def create_user(request: Request, user=Depends(administrator)):
        body = await bounded_json(request)
        if (not isinstance(body, dict) or not {'username', 'password', 'display_name'} <= set(body)
                or set(body) - {'username', 'password', 'display_name', 'role'}):
            raise TaskError('INVALID_REQUEST', '账号请求字段无效', 422)
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(business.accounts.set_user, body['username'], body['password'],
                                      body['display_name'], body.get('role', 'operator'), create_only=True,
                                      actor_id=user['user_id'], token=request.cookies.get(SESSION_COOKIE))

    @routes.patch('/admin/users/{user_id}')
    async def update_user(user_id: uuid.UUID, request: Request, user=Depends(administrator)):
        body = await bounded_json(request)
        from starlette.concurrency import run_in_threadpool
        if isinstance(body, dict) and set(body) == {'display_name'}:
            return await run_in_threadpool(business.accounts.update_display_name, user['user_id'], str(user_id),
                                          body['display_name'], request.cookies.get(SESSION_COOKIE))
        if not isinstance(body, dict) or set(body) != {'enabled'} or type(body['enabled']) is not bool:
            raise TaskError('INVALID_REQUEST', '请单独提交姓名或布尔类型的启用状态', 422)
        return await run_in_threadpool(business.accounts.update_enabled, user['user_id'], str(user_id),
                                      body['enabled'], request.cookies.get(SESSION_COOKIE))

    @routes.delete('/admin/users/{user_id}', status_code=204)
    def delete_user(user_id: uuid.UUID, request: Request, user=Depends(administrator)):
        business.accounts.delete_user(user['user_id'], str(user_id), request.cookies.get(SESSION_COOKIE))
        return Response(status_code=204)

    @routes.post('/admin/users/{user_id}/password', status_code=204)
    async def reset_user_password(user_id: uuid.UUID, request: Request, user=Depends(administrator)):
        body = await bounded_json(request)
        if not isinstance(body, dict) or set(body) != {'new_password'}:
            raise TaskError('INVALID_REQUEST', '密码请求字段无效', 422)
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(business.accounts.reset_password, user['user_id'], str(user_id),
                               body['new_password'], request.cookies.get(SESSION_COOKIE))
        return Response(status_code=204)

    @routes.post('/auth/password', status_code=204)
    async def change_password(request: Request, user=Depends(principal)):
        body = await bounded_json(request)
        if (not isinstance(body, dict) or set(body) != {'current_password', 'new_password'}
                or not isinstance(body['current_password'], str) or not 1 <= len(body['current_password']) <= 128):
            raise TaskError('INVALID_REQUEST', '密码请求字段无效', 422)
        from starlette.concurrency import run_in_threadpool
        await run_in_threadpool(business.accounts.change_password, user['user_id'], body['current_password'],
                               body['new_password'], request.cookies.get(SESSION_COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, httponly=True, secure=request.url.scheme == 'https', samesite='strict', path='/')
        return response

    @routes.get('/doc-types')
    def doc_types(user=Depends(principal)):
        from .doc_profiles import catalogue
        return catalogue(business.store.required_policy()['overrides'])

    @routes.get('/admin/required-fields')
    def required_fields(user=Depends(administrator)):
        from .required_fields import configuration
        return configuration(business.store.required_policy())

    @routes.get('/admin/retention')
    def retention_settings(user=Depends(administrator)):
        from .retention import configuration
        with business.engine.connect() as connection:
            return configuration(connection)

    @routes.put('/admin/retention')
    async def update_retention_settings(request: Request, user=Depends(administrator)):
        from .retention import save_configuration
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(save_configuration, business.store, await bounded_json(request), user['user_id'],
            authorize=lambda connection: business.accounts._acting_user(
                connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=True))

    @routes.put('/admin/required-fields')
    async def update_required_fields(request: Request, user=Depends(administrator)):
        from .required_fields import save_configuration
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(save_configuration, business.store, await bounded_json(request), user['user_id'],
            authorize=lambda connection: business.accounts._acting_user(
                connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=True))

    @routes.get('/batches')
    def batches(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                date_from: date | None = None, date_to: date | None = None, user=Depends(principal)):
        return business.store.batches(page, page_size, date_from, date_to, user=user)

    @routes.post('/classify')
    async def classify_upload(request: Request, user=Depends(operator), slot=Depends(upload_slot)):
        from .document_classification import classify_file
        from starlette.concurrency import run_in_threadpool
        files, _ = await memory_form(request, classification=True)
        result = await run_in_threadpool(classify_file, *files[0])
        with business.engine.connect() as connection:
            authorization(request, user)(connection)
        return result

    @routes.post('/batches', status_code=202)
    async def upload(request: Request, user=Depends(operator), slot=Depends(upload_slot)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请检查引擎状态并重新启动程序', 503)
        files, fields = await memory_form(request)
        if 'expected_revision' in fields:
            raise TaskError('INVALID_REQUEST', '新建材料包不接受追加版本号', 422)
        kind = fields.get('file_types', fields.get('doc_type_hint'))
        # Admission stays off the event loop. Cards use the bounded memory-only
        # safety pass before any durable writes; other types only decode here.
        from starlette.concurrency import run_in_threadpool
        validated = await run_in_threadpool(prepare_uploads, files, kind, runtime)
        return await run_in_threadpool(business.store.create_batch, validated, kind, user['user_id'],
                                      {'abnormal_only': fields.get('abnormal_only', 'false').lower() == 'true'},
                                      person_name=fields.get('person_name'), authorize=authorization(request, user))

    @routes.post('/batches/{batch_id}/append', status_code=202)
    async def append_upload(batch_id: uuid.UUID, request: Request, user=Depends(operator), slot=Depends(upload_slot)):
        with business.engine.connect() as connection:
            business.store._batch_row(connection, str(batch_id), user)
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请检查引擎状态并重新启动程序', 503)
        files, fields = await memory_form(request)
        revision = fields.get('expected_revision', '')
        if 'person_name' in fields or not revision.isascii() or not revision.isdecimal() or len(revision) > 10:
            raise TaskError('INVALID_REQUEST', '请读取材料包最新版本后追加；人员归属不能在追加时变更', 422)
        from starlette.concurrency import run_in_threadpool
        kind = fields.get('file_types', fields.get('doc_type_hint'))
        validated = await run_in_threadpool(prepare_uploads, files, kind, runtime)
        return await run_in_threadpool(business.store.append_batch, str(batch_id), validated, kind,
            int(revision), user['user_id'], {'abnormal_only': fields.get('abnormal_only', 'false').lower() == 'true'},
            user=user, authorize=authorization(request, user))

    @routes.patch('/batches/{batch_id}/person')
    def confirm_person(batch_id: uuid.UUID, body: PersonBody, request: Request, user=Depends(operator)):
        return business.store.confirm_person(str(batch_id), body.person_name, body.expected_revision,
            user['user_id'], user=user, authorize=authorization(request, user))

    @routes.get('/batches/{batch_id}')
    def batch(batch_id: uuid.UUID, user=Depends(principal)):
        return business.store.batch(str(batch_id), user=user)

    @routes.delete('/batches/{batch_id}')
    def delete_batch(batch_id: uuid.UUID, body: DeleteBatchBody, request: Request, user=Depends(administrator)):
        return business.store.delete_batch(str(batch_id), body.model_dump(mode='json')['versions'], user['user_id'],
            authorize=lambda connection: business.accounts._acting_user(
                connection, user['user_id'], request.cookies.get(SESSION_COOKIE), administrator=True))

    @routes.get('/batches/{batch_id}/tasks')
    def batch_tasks(batch_id: uuid.UUID, user=Depends(principal)):
        return business.store.tasks(str(batch_id), user=user)

    @routes.get('/tasks')
    def tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(principal)):
        rows = business.store.tasks(user=user)
        return dict(items=rows[(page-1)*page_size:page*page_size], total=len(rows), page=page, page_size=page_size)

    @routes.get('/tasks/{task_id}')
    def task(task_id: uuid.UUID, user=Depends(principal)):
        return business.store.task(str(task_id), user=user)

    @routes.delete('/tasks/{task_id}')
    def delete_task(task_id: uuid.UUID, body: Version, request: Request, user=Depends(operator)):
        return business.store.delete_task(str(task_id), str(body.run_id), body.expected_revision, user['user_id'],
            user=user, authorize=authorization(request, user))

    @routes.get('/tasks/{task_id}/result')
    def result(task_id: uuid.UUID, items_filter: Literal['all', 'abnormal', 'unknown'] | None = None,
               include_normal_summary: bool = True, user=Depends(principal)):
        return business.store.result(str(task_id), items_filter, include_normal_summary, user=user)

    @routes.post('/tasks/{task_id}/review')
    def review(task_id: uuid.UUID, body: ReviewBody, request: Request, user=Depends(operator)):
        return business.store.review(str(task_id), body.model_dump(mode='json', exclude_unset=True), user['user_id'],
                                     user=user, authorize=authorization(request, user))

    @routes.post('/tasks/{task_id}/ocr-region')
    def region_ocr(task_id: uuid.UUID, body: RegionOCRBody, request: Request, user=Depends(operator)):
        from .region_ocr import transcribe_region
        return transcribe_region(business.store, str(task_id), body.model_dump(mode='json'), user,
                                 authorization(request, user))

    @routes.get('/tasks/{task_id}/preview')
    def preview(task_id: uuid.UUID, run_id: uuid.UUID, request: Request, result_revision: int = Query(ge=0),
                page: int = Query(1, ge=1), stage: Literal['corrected'] = 'corrected',
                masked: bool = True, rendition: Literal['original', 'display'] = 'original', user=Depends(operator)):
        from .preview import corrected_preview
        data = corrected_preview(business.store, str(task_id), str(run_id), result_revision, page,
                                 actor=user['user_id'], role=user['role'], user=user, authorize=authorization(request, user), rendition=rendition)
        return Response(data, media_type='image/png', headers={'X-Preview-Stage': 'corrected', 'X-Result-Revision': str(result_revision), 'X-Preview-Rendition': rendition})

    @routes.post('/tasks/{task_id}/preview')
    def full_preview(task_id: uuid.UUID, body: FullPreview, request: Request, user=Depends(operator)):
        from .preview import corrected_preview
        data = corrected_preview(business.store, str(task_id), str(body.run_id), body.expected_revision, body.page,
                                 actor=user['user_id'], role=user['role'], masked=False, access_reason=body.reason,
                                 user=user, authorize=authorization(request, user), rendition=body.rendition)
        return Response(data, media_type='image/png', headers={'X-Preview-Stage': 'corrected', 'X-Result-Revision': str(body.expected_revision), 'X-Preview-Rendition': body.rendition})

    @routes.post('/tasks/{task_id}/reveal')
    def reveal(task_id: uuid.UUID, body: RevealBody, request: Request, user=Depends(operator)):
        from .preview import reveal_fields
        return reveal_fields(business.store, str(task_id), body.model_dump(mode='json'), user['user_id'], user['role'],
                             user=user, authorize=authorization(request, user))

    @routes.post('/export')
    def export(body: ExportBody, request: Request, user=Depends(operator), slot=Depends(export_slot)):
        from .exporting import export_results
        from urllib.parse import quote
        from .audit import CONTEXT
        context = CONTEXT.get()
        if context is not None:
            context['export_targets'] = ([dict(batch_id=str(body.batch_id))] if body.batch_id else
                                         [dict(task_id=str(identifier)) for identifier in body.task_ids or []]) or [{}]
        data, media, filename = export_results(business.store, body.model_dump(mode='json', exclude_none=True), user['user_id'], user['role'],
                              user=user, authorize=authorization(request, user), with_metadata=True)
        return Response(data, media_type=media,
                        headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')})

    @routes.post('/tasks/{task_id}/cancel', status_code=202)
    def cancel(task_id: uuid.UUID, version: Version, request: Request, user=Depends(operator)):
        return business.store.cancel(str(task_id), str(version.run_id), version.expected_revision, user['user_id'],
                                     user=user, authorize=authorization(request, user))

    @routes.post('/tasks/{task_id}/rerun', status_code=202)
    def rerun(task_id: uuid.UUID, version: Version, request: Request, user=Depends(operator)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请先重新启动程序', 503)
        return business.store.rerun(str(task_id), str(version.run_id), version.expected_revision, user['user_id'],
                                    user=user, authorize=authorization(request, user))

    public.include_router(routes)
    return public
