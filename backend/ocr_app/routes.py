"""Authenticated phase-two routes. Upload parsing is explicitly memory-only."""
import uuid
import hmac
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from .business import prepare_uploads
from .task_store import TaskError, SUPPORTED
from .auth import SESSION_COOKIE, SESSION_SECONDS, same_origin, csrf_for
from .upload_limits import MAX_FILES, MAX_FILE_BYTES, MAX_BATCH_BYTES


class Version(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: uuid.UUID
    expected_revision: int = Field(ge=0, strict=True)


class ReviewBody(Version):
    fields: dict = Field(default_factory=dict)
    absence_reasons: dict = Field(default_factory=dict)
    accepted_issues: list[dict] = Field(default_factory=list)
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
    note: str | None = Field(default=None, max_length=1000)


class DeleteTaskVersion(Version):
    task_id: uuid.UUID


class DeleteBatchBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    versions: list[DeleteTaskVersion] = Field(min_length=1, max_length=100)


class FullPreview(Version):
    page: int = Field(default=1, ge=1)
    reason: str | None = Field(default=None, max_length=1000)


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


async def memory_form(request):
    media, options = parse_options_header(request.headers.get('content-type', ''))
    boundary = options.get(b'boundary')
    if media != b'multipart/form-data' or not boundary or len(boundary) > 200:
        raise TaskError('INVALID_REQUEST', '请使用文件上传表单', 400)
    files, fields, current, header, ended = [], {}, {}, {}, [False]

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
            if len(files) >= MAX_FILES:
                raise TaskError('FILE_TOO_LARGE', '每批最多100个文件', 413)
            if sum(len(data) for data, _ in files) + len(current['body']) > MAX_BATCH_BYTES:
                raise TaskError('FILE_TOO_LARGE', '单次上传总大小不超过500MB', 413)
            files.append((bytes(current['body']), values[b'filename'].decode('utf-8', errors='strict')))
        elif name in {'doc_type_hint', 'abnormal_only'} and len(current['body']) <= 64 and name not in fields:
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
            if size > MAX_BATCH_BYTES + (MAX_FILES + 2) * 8192:
                raise TaskError('FILE_TOO_LARGE', '单次上传总大小不超过500MB', 413)
            parser.write(chunk)
        parser.finalize()
    except TaskError:
        raise
    except Exception as error:
        raise TaskError('INVALID_REQUEST', '上传表单不完整或编码无效', 400) from error
    if not ended[0] or not files:
        raise TaskError('INVALID_REQUEST', '上传表单不完整', 400)
    if fields.get('doc_type_hint') not in SUPPORTED:
        raise TaskError('UNSUPPORTED_DOC_TYPE', '材料类型未受支持，请从材料目录选择', 422)
    if fields.get('abnormal_only', 'false').lower() not in {'true', 'false'}:
        raise TaskError('INVALID_REQUEST', '异常项目开关无效', 400)
    return files, fields


def router(business, runtime):
    routes = APIRouter(prefix='/api/v1')

    def principal(request: Request):
        token = request.cookies.get(SESSION_COOKIE)
        user = business.accounts.session(token)
        request.state.csrf_token = csrf_for(token) if user else None
        if user and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            same_origin(request)
            provided = request.headers.get('X-CSRF-Token', '')
            if not provided.isascii() or not hmac.compare_digest(provided, request.state.csrf_token):
                raise TaskError('FORBIDDEN', '登录校验已变化，请刷新工作台后再试', 403)
        if not user:
            user = business.accounts.authenticate(request.headers.get('X-API-Key'))
        if not user:
            raise TaskError('UNAUTHORIZED', '请登录工作台', 401)
        return user

    def operator(user=Depends(principal)):
        if user['role'] not in {'operator', 'admin'}:
            raise TaskError('FORBIDDEN_REVEAL', '当前账号无此操作权限', 403)
        return user

    def administrator(user=Depends(principal)):
        if user['role'] != 'admin':
            raise TaskError('FORBIDDEN', '只有管理员可以修改管理设置', 403)
        return user

    @routes.get('/auth/me')
    def me(request: Request, user=Depends(principal)):
        payload=dict(user, permissions=['rerun', 'review', 'reveal', 'export'] if user['role'] != 'viewer' else [])
        if request.state.csrf_token:
            payload['csrf_token']=request.state.csrf_token
        return payload

    @routes.post('/auth/login')
    async def login(request: Request):
        same_origin(request)
        body=await bounded_json(request)
        if (not isinstance(body,dict) or set(body)!={'username','password'} or
                not isinstance(body['username'],str) or not 1<=len(body['username'])<=64 or
                not isinstance(body['password'],str) or not 1<=len(body['password'])<=128):
            raise TaskError('INVALID_REQUEST', '登录请求无效', 422)
        from starlette.concurrency import run_in_threadpool
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

    @routes.put('/admin/required-fields')
    async def update_required_fields(request: Request, user=Depends(administrator)):
        from .required_fields import save_configuration
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(save_configuration, business.store, await bounded_json(request), user['user_id'])

    @routes.get('/batches')
    def batches(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                date_from: date | None = None, date_to: date | None = None, user=Depends(principal)):
        return business.store.batches(page, page_size, date_from, date_to, user=user)

    @routes.post('/batches', status_code=202)
    async def upload(request: Request, user=Depends(operator)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请检查引擎状态并重新启动程序', 503)
        files, fields = await memory_form(request)
        # Admission stays off the event loop. Cards use the bounded memory-only
        # safety pass before any durable writes; other types only decode here.
        from starlette.concurrency import run_in_threadpool
        validated = await run_in_threadpool(prepare_uploads, files, fields['doc_type_hint'], runtime)
        return await run_in_threadpool(business.store.create_batch, validated, fields['doc_type_hint'], user['user_id'],
                                      {'abnormal_only': fields.get('abnormal_only', 'false').lower() == 'true'})

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

    @routes.get('/tasks/{task_id}/result')
    def result(task_id: uuid.UUID, items_filter: Literal['all', 'abnormal', 'unknown'] | None = None,
               include_normal_summary: bool = True, user=Depends(principal)):
        return business.store.result(str(task_id), items_filter, include_normal_summary, user=user)

    @routes.post('/tasks/{task_id}/review')
    def review(task_id: uuid.UUID, body: ReviewBody, user=Depends(operator)):
        return business.store.review(str(task_id), body.model_dump(mode='json', exclude_unset=True), user['user_id'], user=user)

    @routes.get('/tasks/{task_id}/preview')
    def preview(task_id: uuid.UUID, run_id: uuid.UUID, result_revision: int = Query(ge=0),
                page: int = Query(1, ge=1), stage: Literal['corrected'] = 'corrected',
                masked: bool = True, user=Depends(principal)):
        from .preview import corrected_preview
        data = corrected_preview(business.store, str(task_id), str(run_id), result_revision, page,
                                 actor=user['user_id'], role=user['role'], user=user)
        return Response(data, media_type='image/png', headers={'X-Preview-Stage': 'corrected', 'X-Result-Revision': str(result_revision)})

    @routes.post('/tasks/{task_id}/preview')
    def full_preview(task_id: uuid.UUID, body: FullPreview, user=Depends(operator)):
        from .preview import corrected_preview
        data = corrected_preview(business.store, str(task_id), str(body.run_id), body.expected_revision, body.page,
                                 actor=user['user_id'], role=user['role'], masked=False, access_reason=body.reason, user=user)
        return Response(data, media_type='image/png', headers={'X-Preview-Stage': 'corrected', 'X-Result-Revision': str(body.expected_revision)})

    @routes.post('/tasks/{task_id}/reveal')
    def reveal(task_id: uuid.UUID, body: RevealBody, user=Depends(operator)):
        from .preview import reveal_fields
        return reveal_fields(business.store, str(task_id), body.model_dump(mode='json'), user['user_id'], user['role'], user=user)

    @routes.post('/export')
    def export(body: ExportBody, user=Depends(principal)):
        from .exporting import export_results
        data = export_results(business.store, body.model_dump(mode='json', exclude_none=True), user['user_id'], user['role'], user=user)
        return Response(data, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="reviewed-results.xlsx"'})

    @routes.post('/tasks/{task_id}/cancel', status_code=202)
    def cancel(task_id: uuid.UUID, version: Version, user=Depends(operator)):
        return business.store.cancel(str(task_id), str(version.run_id), version.expected_revision, user['user_id'], user=user)

    @routes.post('/tasks/{task_id}/rerun', status_code=202)
    def rerun(task_id: uuid.UUID, version: Version, user=Depends(operator)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请先重新启动程序', 503)
        return business.store.rerun(str(task_id), str(version.run_id), version.expected_revision, user['user_id'], user=user)

    return routes
