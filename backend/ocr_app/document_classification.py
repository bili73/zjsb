"""Editable material suggestions; bounded CPU OCR, no tasks or plaintext files."""
from functools import lru_cache
import hashlib
import io
from pathlib import Path, PureWindowsPath
import re
import threading
import unicodedata

from .business import validate_upload

_lock = threading.Lock()
_models = {
    'Det': ('PP-OCRv6_det_small.onnx', '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f'),
    'Cls': ('ch_ppocr_mobile_v2.0_cls_mobile.onnx', 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c'),
    'Rec': ('PP-OCRv6_rec_small.onnx', '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'),
}


def _compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).upper()


def content_types(text):
    """Closed headers/features, never a best-effort GENERIC assignment."""
    t = _compact(text)
    kinds = set()
    if any(word in t for word in ('应聘登记表', '面试登记表')):
        kinds.add('INTERVIEW_FORM')
        t = ''  # Form labels may mention other documents without containing them.
    if '教育部学历证书电子注册备案表' in t:
        kinds.add('XUEXIN_DIPLOMA_TABLE')
        # These reports contain school/degree/certificate words as data.
        t = ''
    elif any(word in t for word in ('学籍在线验证报告', '学位在线验证报告', '中国高等教育学历认证报告')):
        return set(), True
    if '公民身份号码' in t and sum(word in t for word in ('姓名', '性别', '民族', '住址')) >= 2:
        kinds.add('ID_CARD_FRONT')
    if '签发机关' in t and '有效期限' in t:
        kinds.add('ID_CARD_BACK')
    if re.search(r'毕业证(?:书)?', t):
        kinds.add('DIPLOMA')
    if '学位证书' in t or re.search(r'(?:学士|硕士|博士)学位(?:证|授予)', t):
        kinds.add('DEGREE_CERT')
    if any(word in t for word in ('体检报告', '健康检查报告', '生化检验报告单', '体检结果', '健康体检', '体检中心', '本次体检项目意义')):
        kinds.add('MEDICAL_REPORT')
    if '营业执照' in t:
        kinds.add('BUSINESS_LICENSE')
    if '护照' in t and ('PASSPORT' in t or '中华人民共和国' in t) or re.search(r'P<CHN[A-Z<]{20,}', t):
        kinds.add('PASSPORT')
    if any(word in t for word in ('居民户口簿', '户口登记簿', '常住人口登记卡')):
        kinds.add('HOUSEHOLD_REGISTER')
    if not kinds.intersection({'ID_CARD_FRONT', 'ID_CARD_BACK'}) and (
        any(word in t for word in ('储蓄卡', '借记卡', '信用卡', 'DEBIT', 'CREDIT', 'UNIONPAY'))
        or '银行' in t and re.search(r'(?<![0-9])[0-9]{13,19}(?![0-9X])', t)
    ):
        kinds.add('BANK_CARD')
    return kinds, False


def filename_types(name):
    t = _compact(PureWindowsPath(name.replace('/', '\\')).stem)
    kinds = set()
    for kind, words in {
        'INTERVIEW_FORM': ('面试登记表', '应聘登记表'),
        'DIPLOMA': ('毕业证',), 'DEGREE_CERT': ('学位证',), 'BANK_CARD': ('银行卡', '储蓄卡', '借记卡'),
        'MEDICAL_REPORT': ('体检报告', '体检表'), 'BUSINESS_LICENSE': ('营业执照',),
        'PASSPORT': ('护照',), 'HOUSEHOLD_REGISTER': ('户口本', '户口簿'),
        'XUEXIN_DIPLOMA_TABLE': ('学历证书电子注册备案表',),
    }.items():
        if any(word in t for word in words):
            kinds.add(kind)
    if '身份证' in t:
        if any(word in t for word in ('正反面', '正背面', '双面', '两面')):
            kinds.update(('ID_CARD_FRONT', 'ID_CARD_BACK'))
        if any(word in t for word in ('人像', '正面')):
            kinds.add('ID_CARD_FRONT')
        if any(word in t for word in ('国徽', '背面', '反面')):
            kinds.add('ID_CARD_BACK')
    return kinds


def suggestion(text, name, fallback_reason='内容不足，请核对原件并选择类型'):
    kinds, unsupported = content_types(text)
    hints = filename_types(name)
    if unsupported or len(kinds) > 1:
        return dict(doc_type=None, basis='unknown', candidates=sorted(kinds),
                    reason='检测到多种材料或暂不支持的报告，请拆分或手动选择')
    if kinds:
        return dict(doc_type=next(iter(kinds)), basis='content', candidates=sorted(kinds),
                    reason='已根据文件内容建议类型，请核对' if not hints or hints == kinds else '内容与文件名提示不同，请核对类型')
    if len(hints) == 1:
        return dict(doc_type=next(iter(hints)), basis='filename', candidates=sorted(hints),
                    reason='仅根据文件名建议类型，请核对原件')
    return dict(doc_type=None, basis='unknown', candidates=sorted(hints), reason=fallback_reason)


@lru_cache(maxsize=1)
def _engine():
    import rapidocr
    directory = Path(rapidocr.__file__).resolve().parent / 'models'
    params = {'Global.log_level': 'critical', 'EngineConfig.onnxruntime.intra_op_num_threads': 2,
              'EngineConfig.onnxruntime.inter_op_num_threads': 1, 'Det.limit_side_len': 736,
              'Det.limit_type': 'max', 'Det.max_candidates': 500}
    # Explicit bundled paths prohibit request-time asset downloads.
    for section, (name, digest) in _models.items():
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('CLASSIFICATION_ASSET_MISMATCH')
        params[section + '.model_path'] = str(path)
    return rapidocr.RapidOCR(params=params)


def _ocr(image):
    import numpy as np
    image.thumbnail((1600, 1600))
    result = _engine()(np.asarray(image.convert('RGB')))
    return '\n'.join(result.txts or ())


def classify_file(data, name):
    admitted = validate_upload(data, name)
    if not _lock.acquire(blocking=False):
        return suggestion('', name, '自动分类正在忙，可手动选择或稍后重试')
    try:
        from PIL import Image, ImageOps
        texts = []
        if admitted['mime'] == 'application/pdf':
            import fitz
            with fitz.open(stream=data, filetype='pdf') as document:
                for index in range(min(2, document.page_count)):
                    page = document[index]
                    text = page.get_text()[:30000]
                    if not content_types(text)[0] and not content_types(text)[1]:
                        scale = min(2., 1600 / max(page.rect.width, page.rect.height))
                        pixels = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
                        text += '\n' + _ocr(Image.frombytes('RGB', (pixels.width, pixels.height), pixels.samples))
                    texts.append(text)
        else:
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1600, 1600))
            text = _ocr(image)
            kinds, unsupported = content_types(text)
            if not kinds and not unsupported:
                text += '\n' + _ocr(image.rotate(90, expand=True))
            texts.append(text)
        observed = set().union(*(content_types(text)[0] for text in texts))
        if len(observed) > 1 or any(content_types(text)[1] for text in texts):
            return dict(doc_type=None, basis='unknown', candidates=sorted(observed),
                        reason='检测到多种材料或暂不支持的报告，请拆分或手动选择')
        return suggestion('\n'.join(texts), name)
    except Exception:
        # No PII-bearing exception/text logs. Admission errors already fail above.
        return suggestion('', name, '自动分类暂不可用，请手动选择类型')
    finally:
        _lock.release()
