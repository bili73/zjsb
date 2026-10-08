"""Authenticated phase-two routes. Upload parsing is explicitly memory-only."""
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from python_multipart import MultipartParser
from python_multipart.multipart import parse_options_header

from .business import validate_upload
from .task_store import TaskError, SUPPORTED


class Version(BaseModel):
    model_config = ConfigDict(extra='forbid')
    run_id: uuid.UUID
    expected_revision: int = Field(ge=0)


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
        if len(current['body']) + end - start > 10 * 1024 * 1024:
            raise TaskError('FILE_TOO_LARGE', '单文件不超过10MB', 413)
        current['body'].extend(data[start:end])

    def part_end():
        _, values = parse_options_header(current['headers'].get(b'content-disposition', b''))
        name = values.get(b'name', b'').decode('utf-8', errors='strict')
        if name == 'files' and b'filename' in values:
            if len(files) >= 20:
                raise TaskError('FILE_TOO_LARGE', '每批最多20个文件', 413)
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
            if size > 50 * 1024 * 1024 + 65536:
                raise TaskError('FILE_TOO_LARGE', '单次上传总大小不超过50MB', 413)
            parser.write(chunk)
        parser.finalize()
    except TaskError:
        raise
    except Exception as error:
        raise TaskError('INVALID_REQUEST', '上传表单不完整或编码无效', 400) from error
    if not ended[0] or not files or sum(len(data) for data, _ in files) > 50 * 1024 * 1024:
        raise TaskError('INVALID_REQUEST', '上传表单不完整或超出容量', 400)
    if fields.get('doc_type_hint') not in SUPPORTED:
        raise TaskError('UNSUPPORTED_DOC_TYPE', '本阶段仅接收体检报告、毕业证和学位证；不接收银行卡', 422)
    if fields.get('abnormal_only', 'false').lower() not in {'true', 'false'}:
        raise TaskError('INVALID_REQUEST', '异常项目开关无效', 400)
    return files, fields


def router(business, runtime):
    routes = APIRouter(prefix='/api/v1')

    def principal(request: Request):
        user = business.accounts.authenticate(request.headers.get('X-API-Key'))
        if not user:
            raise TaskError('INVALID_REQUEST', '访问密钥无效或缺失', 401)
        return user

    def operator(user=Depends(principal)):
        if user['role'] not in {'operator', 'admin'}:
            raise TaskError('FORBIDDEN_REVEAL', '当前账号无此操作权限', 403)
        return user

    @routes.get('/auth/me')
    def me(user=Depends(principal)):
        return dict(user, permissions=['rerun'] if user['role'] != 'viewer' else [])

    @routes.get('/batches')
    def batches(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(principal)):
        return business.store.batches(page, page_size)

    @routes.post('/batches', status_code=202)
    async def upload(request: Request, user=Depends(operator)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请检查引擎状态并重新启动程序', 503)
        files, fields = await memory_form(request)
        # Decoding is isolated from the event loop; uploads never start model inference.
        from starlette.concurrency import run_in_threadpool
        validated = await run_in_threadpool(lambda: [validate_upload(data, name) for data, name in files])
        return await run_in_threadpool(business.store.create_batch, validated, fields['doc_type_hint'], user['user_id'],
                                      {'abnormal_only': fields.get('abnormal_only', 'false').lower() == 'true'})

    @routes.get('/batches/{batch_id}')
    def batch(batch_id: uuid.UUID, user=Depends(principal)):
        return business.store.batch(str(batch_id))

    @routes.get('/batches/{batch_id}/tasks')
    def batch_tasks(batch_id: uuid.UUID, user=Depends(principal)):
        business.store.batch(str(batch_id))
        return business.store.tasks(str(batch_id))

    @routes.get('/tasks')
    def tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user=Depends(principal)):
        rows = business.store.tasks()
        return dict(items=rows[(page-1)*page_size:page*page_size], total=len(rows), page=page, page_size=page_size)

    @routes.get('/tasks/{task_id}')
    def task(task_id: uuid.UUID, user=Depends(principal)):
        return business.store.task(str(task_id))

    @routes.get('/tasks/{task_id}/result')
    def result(task_id: uuid.UUID, items_filter: Literal['all', 'abnormal', 'unknown'] | None = None,
               include_normal_summary: bool = True, user=Depends(principal)):
        return business.store.result(str(task_id), items_filter, include_normal_summary)

    @routes.post('/tasks/{task_id}/cancel', status_code=202)
    def cancel(task_id: uuid.UUID, version: Version, user=Depends(operator)):
        return business.store.cancel(str(task_id), str(version.run_id), version.expected_revision, user['user_id'])

    @routes.post('/tasks/{task_id}/rerun', status_code=202)
    def rerun(task_id: uuid.UUID, version: Version, user=Depends(operator)):
        if not runtime.is_alive():
            raise TaskError('INTERNAL_ERROR', '处理服务不可用，请先重新启动程序', 503)
        return business.store.rerun(str(task_id), str(version.run_id), version.expected_revision, user['user_id'])

    return routes
