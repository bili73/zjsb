"""One-photo table workflow inside the existing supervised document process."""
import base64
import hashlib
import time
from uuid import uuid4

from .documents import decode_pages, DocumentError, normalized_box, png_bytes
from .extraction import issue
from .table_recognition import candidate_image, decode_table_output, grid_dimensions_hint, infer_header_rows, locate_table_candidates, nearby_text


def process_photo_table(content, *, recognize, progress, save_page, record_attempt, cancelled, deadline):
    pages, tables, warnings = [], [], []
    error = None
    stage = 'PREPROCESSING'
    def check():
        if cancelled():
            raise DocumentError('CANCELLED')
        if time.monotonic() >= deadline:
            raise DocumentError('EXTRACT_TIMEOUT')
    def publish(next_stage):
        nonlocal stage
        stage = next_stage
        check()
        progress(stage, 0, pages)
    try:
        publish('PREPROCESSING')
        if content.lstrip().startswith(b'%PDF-'):
            raise DocumentError('UNSUPPORTED_FORMAT')
        page = next(iter(decode_pages(content, check, preprocessing={'doc_type':'TABLE'})))
        page_id = save_page(1, png_bytes(page.image), page.image.width, page.image.height)
        region_id = str(uuid4())
        info = dict(page_id=page_id, page_index=1, width=page.image.width, height=page.image.height,
                    extraction_method='pending', regions=[], _preparation_complete=True)
        if page.image_preprocessing:
            info['image_preprocessing'] = page.image_preprocessing
            if page.image_preprocessing.get('warning'):
                warnings.append(dict(code=page.image_preprocessing['warning'],message='图片自动摆正未能完全确认，请核对原图方向。'))
        pages.append(info)
        candidates = locate_table_candidates(page.image, check)
        snippets = nearby_text(page.image, candidates, check)
        chosen = candidates[0] if candidates else dict(box=[0,0,*page.image.size],quad=None)
        pixels, transform = candidate_image(page.image, chosen)
        box = chosen['box']; width,height = page.image.size
        titles = [t for t in snippets if box[0] <= (t['box'][0]+t['box'][2])/2 <= box[2]
                  and box[1]-height*.16 < (t['box'][1]+t['box'][3])/2 < box[1]+8]
        # Font height and distance suggest candidates; never a fixed business title.
        titles.sort(key=lambda t:(t['box'][3]-t['box'][1])/max(1.,abs(box[1]-(t['box'][1]+t['box'][3])/2)),reverse=True)
        outside = [t for t in snippets if box[3]-8 < (t['box'][1]+t['box'][3])/2 < box[3]+height*.2]
        quality = ['请对照原图核对手写、划除内容及表外补录；空白格不代表漏识别。']
        if not candidates:
            quality.append('未确定表格边界，当前按整图识别，可调整主体裁剪后新建任务。')
        elif len(candidates)>1:
            quality.append('检测到多个表格候选，请确认选中的主体；其他候选可裁剪后另建任务。')
        table = dict(table_id=str(uuid4()),title='',title_candidates=titles[:4],header_rows=None,header_suggestion=None,header_suggestion_source=None,
                     rows=[['']],merges=[],partial_acknowledged=False,confidence=None,incomplete=True,
                     source=dict(page=1,region_id=region_id,bbox=normalized_box(box,page.image.size),extraction_method='ocr'),
                     candidates=[dict(bbox=normalized_box(c['box'],page.image.size)) for c in candidates],
                     outside_text=outside,quality_warnings=quality)
        tables.append(table)
        region = dict(region_id=region_id,bbox=table['source']['bbox'],extraction_method='ocr',status='pending')
        info['regions'].append(region)
        png = png_bytes(pixels)
        for index,model in enumerate(('paddleocr_vl','glm_ocr'),1):
            publish('OCR')
            began=time.monotonic(); prediction={}; decoded=[]; failure=None
            attempt=dict(page_index=1,region_id=region_id,bbox=region['bbox'],attempt=index,model=model,task='table',
                         input_sha256=hashlib.sha256(png).hexdigest(),transform='auto_table_perspective' if transform else 'auto_table_crop',
                         perspective_transform=transform,prompt='Table Recognition:',max_new_tokens=4096,
                         generation_timeout_seconds=40.,timeout_seconds=max(.001,deadline-began),cache_hit=False,inference_performed=True)
            try:
                prediction=recognize(model,base64.b64encode(png).decode('ascii'),'table',max(.001,deadline-time.monotonic()),
                                     max_new_tokens=4096,generation_timeout_seconds=40.,context={'page':1,'region_id':region_id,'stage':'OCR'})
                decoded=decode_table_output(prediction.get('text',''))
            except Exception as exc:
                failure=getattr(exc,'code',None) or 'TABLE_STRUCTURE_INVALID'
                if failure=='SUPERVISION_FAILED':
                    raise
            complete=bool(decoded) and prediction.get('termination_reason')=='eos' and not prediction.get('error_code') and not failure
            record_attempt({**attempt,'prediction':prediction,'status':'completed' if complete else 'incomplete',
                            'error_code':failure,'elapsed_seconds':time.monotonic()-began})
            if decoded:
                selected=max(decoded,key=lambda t:len(t['rows'])*len(t['rows'][0]))
                header_count, header_source = infer_header_rows(selected) if complete else (None, None)
                table.update(rows=selected['rows'],merges=selected['merges'],header_suggestion=header_count,
                             header_suggestion_source=header_source,incomplete=not complete or bool(selected['warnings']))
                if selected['warnings']:
                    table['quality_warnings'].append('模型返回的各行列数不一致，已保留所有内容并补空格对齐；请检查错列或缺格。')
                if len(decoded)>1:
                    table['quality_warnings'].append('模型返回多个表格，当前展示最大表格；请核对原件和原始识别记录。')
                    table['incomplete']=True
            if failure in {'MODEL_REQUEST_TIMEOUT','EXTRACT_TIMEOUT'}:
                raise DocumentError('EXTRACT_TIMEOUT')
            check()
            if complete:
                break
        region['status']='incomplete' if table['incomplete'] else 'recognized'
        info['extraction_method']='ocr'
        if table['incomplete']:
            table['quality_warnings'].append('识别未完整结束或结构不可靠，请补齐并明确确认后导出。')
        hint=grid_dimensions_hint(pixels)
        if any(hint[i]>n for i,n in enumerate((len(table['rows']),len(table['rows'][0])))):
            table['quality_warnings'].append('可见长线框比识别结果包含更多行或列，请检查是否漏格；线框估计可能受拍摄角度影响。')
            table['incomplete']=True
            region['status']='incomplete'
        if table['incomplete']:
            table.update(header_suggestion=None, header_suggestion_source=None)
        publish('VALIDATING')
    except DocumentError as exc:
        error=dict(code=exc.code,message='表格处理未完成，已保留可用结果。',stage=stage)
    status='CANCELLED' if error and error['code']=='CANCELLED' else 'FAILED' if error else 'NEED_REVIEW'
    return dict(doc_type='TABLE',status=status,pages=pages,fields=[],tables=tables,review_issues=[issue('UNKNOWN','请对照原图确认主体、标题、表头和单元格。')],
                limitations=['表外手写记录可能无法完整识别，请核对完整原图。'],warnings=warnings,**({'error':error} if error else {}))
