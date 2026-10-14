"""CPU certificate/card-photo orientation; originals and uncertain directions survive."""
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import time

from PIL import Image, ImageOps

MODEL_REVISION = '7330ab7039123e46af2dc03154b9969aa412c61d'
MODEL_SHA256 = 'af9a0a4f317ff0709ce752067807f819cb15d883f8ecad89f28df1c6ee2d9c92'
MODEL_URL = f'https://huggingface.co/PaddlePaddle/PP-LCNet_x1_0_doc_ori_onnx/resolve/{MODEL_REVISION}/inference.onnx'
MODEL_PATH = Path(__file__).resolve().parents[2] / 'models/pp-lcnet-doc-ori/inference.onnx'
VERSION = 'certificate-upright-v1'
MAX_CORRECTED_PIXELS = 40_000_000
UPRIGHT_DOCUMENT_TYPES = frozenset({
    'DIPLOMA', 'DEGREE_CERT', 'ID_CARD_FRONT', 'ID_CARD_BACK', 'BANK_CARD',
    'BUSINESS_LICENSE', 'XUEXIN_DIPLOMA_TABLE', 'PASSPORT', 'HOUSEHOLD_REGISTER', 'GENERIC',
})


@lru_cache(maxsize=1)
def _session():
    import onnxruntime as ort
    if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
        raise ValueError('ORIENTATION_MODEL_HASH_MISMATCH')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    try:
        return ort.InferenceSession(str(MODEL_PATH), sess_options=options, providers=['CPUExecutionProvider'])
    except Exception as exc:
        raise RuntimeError('ORIENTATION_MODEL_UNAVAILABLE') from exc


def classify_orientation(image):
    """Require agreeing center/full-page views; scores remain uncalibrated."""
    session = _session()
    center = _classify_view(image, session)
    whole = _classify_view(ImageOps.pad(image, (256, 256), color='white'), session)
    if center[0] != whole[0]:
        return 0, 0., 0.
    return center[0], max(center[1], whole[1]), min(center[2], whole[2])


def _confident(prediction):
    return prediction[1] >= .9 and prediction[2] >= .25


def _bank_card_view(image, check=lambda: None):
    """Find a card-like contour for direction analysis, never crop the OCR page."""
    import cv2
    import numpy as np
    check()
    probe = image.copy()
    probe.thumbnail((1000, 1000))
    pixels = np.asarray(probe)
    gray = cv2.GaussianBlur(cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    saturation = cv2.cvtColor(pixels, cv2.COLOR_RGB2HSV)[:, :, 1]
    masks = [cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1],
             cv2.threshold(saturation, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1],
             cv2.Canny(gray, 40, 120)]
    candidates = []
    for mask in masks:
        check()
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        contours = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:20]:
            check()
            area = cv2.contourArea(contour)
            width, height = cv2.minAreaRect(contour)[1]
            if min(width, height) < 10:
                continue
            fraction = area / (probe.width * probe.height)
            extent = area / (width * height)
            if not (.03 < fraction < .98 and 1.25 < max(width, height) / min(width, height) < 2.3 and extent > .65):
                continue
            x, y, w, h = cv2.boundingRect(contour)
            margin = max(3, round(min(w, h) * .03))
            box = (max(0, x - margin), max(0, y - margin),
                   min(probe.width, x + w + margin), min(probe.height, y + h + margin))
            candidates.append((extent * min(fraction, .4), box))
    check()
    return probe.crop(max(candidates, key=lambda candidate: candidate[0])[1]) if candidates else None


def classify_bank_orientation(image, check=lambda: None):
    """Resolve direction from a card view, then compose any analysis-only turn."""
    crop = _bank_card_view(image, check)
    check()
    if crop is None:
        return classify_orientation(image)
    prediction = classify_orientation(crop)
    check()
    if _confident(prediction):
        return prediction
    turn = 90 if crop.height > crop.width else 0
    landscape = crop.transpose(Image.Transpose.ROTATE_90) if turn else crop
    if turn:
        prediction = classify_orientation(landscape)
        check()
        if prediction[0] in {0, 180} and _confident(prediction):
            return (turn + prediction[0]) % 360, prediction[1], prediction[2]
    prediction = classify_orientation(ImageOps.expand(landscape, border=12, fill='white'))
    check()
    if prediction[0] in {0, 180} and _confident(prediction):
        return (turn + prediction[0]) % 360, prediction[1], prediction[2]
    return 0, 0., 0.


def _classify_view(image, session):
    """Follow official inference.yml, using RGB and its fixed label order."""
    import cv2
    import numpy as np
    pixels = np.asarray(image.convert('RGB'))
    height, width = pixels.shape[:2]
    scale = 256 / min(height, width)
    resized = cv2.resize(pixels, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_LINEAR)
    top, left = (resized.shape[0] - 224) // 2, (resized.shape[1] - 224) // 2
    tensor = resized[top:top + 224, left:left + 224].astype('float32') / 255
    tensor = ((tensor - np.array([.485, .456, .406], dtype='float32')) /
              np.array([.229, .224, .225], dtype='float32')).transpose(2, 0, 1)[None]
    scores = np.asarray(session.run(None, {session.get_inputs()[0].name: tensor})[0]).reshape(-1)
    if len(scores) != 4 or not np.isfinite(scores).all() or np.any(scores < 0) or abs(float(scores.sum()) - 1) > .01:
        raise ValueError('ORIENTATION_OUTPUT_INVALID')
    ranked = np.argsort(scores)
    return int(ranked[-1]) * 90, float(scores[ranked[-1]]), float(scores[ranked[-1]] - scores[ranked[-2]])


def apply_correction(image, decision):
    """Reuse the exact plan in pass two; right-angle transposes never resample."""
    angle = decision.get('rotation_degrees', 0)
    transpose = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_270}
    if angle:
        image = image.transpose(transpose[angle])
    skew = decision.get('deskew_degrees', 0.)
    if skew:
        image = image.rotate(skew, resample=Image.Resampling.BICUBIC, expand=True, fillcolor='white')
    return image


def estimate_skew(image, check=lambda: None):
    """Bounded projection search on text-sized components; conflicting halves abstain."""
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    probe = image.convert('L')
    probe.thumbnail((1000, 1000))
    pixels = np.asarray(probe)
    binary = cv2.threshold(pixels, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    height, width = binary.shape
    keep = np.zeros(count, dtype='uint8')
    for i, (_, _, w, h, area) in enumerate(stats[1:], 1):
        if 3 <= h <= height * .065 and 1 <= w <= width * .12 and 4 <= area <= height * width * .003 and w / h < 12:
            keep[i] = 1
    mask = keep[labels].astype('float32')
    if int(keep.sum()) < 20 or not .002 <= float(mask.mean()) <= .25:
        return 0., 'insufficient_text'

    def best_angle(part):
        h, w = part.shape
        def score(angle):
            matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.)
            rotated = cv2.warpAffine(part, matrix, (w, h), flags=cv2.INTER_NEAREST)
            return float(np.var(rotated.sum(axis=1)))
        original = score(0.)
        best, peak = 0., original
        for step in range(-24, 25):
            check()
            angle = step / 2
            value = score(angle)
            if value > peak:
                best, peak = angle, value
        return best, peak / max(original, .001)

    angle, gain = best_angle(mask)
    if abs(angle) < .5:
        return 0., 'already_level'
    if abs(angle) >= 12 or gain < 1.15:
        return 0., 'skew_uncertain'
    halves = [mask[:height // 2], mask[height // 2:]]
    estimates = [best_angle(part) for part in halves if float(part.mean()) >= .002]
    if len(estimates) != 2 or any(abs(candidate - angle) > 1 or improvement < 1.1 for candidate, improvement in estimates):
        return 0., 'skew_uncertain'
    return angle, 'deskew_applied'


def prepare_image(image, check=lambda: None, *, doc_type=None):
    """Classification scores are uncalibrated orientation evidence, never OCR confidence."""
    started = time.monotonic()
    decision = dict(version='bank-card-upright-v1' if doc_type == 'BANK_CARD' else VERSION,
                    model_sha256=MODEL_SHA256, rotation_degrees=0, deskew_degrees=0.,
                    orientation_score=None, orientation_margin=None, status='unchanged', warning=None)
    check()
    extrema = image.convert('L').getextrema()
    if extrema[1] - extrema[0] < 16 or min(image.size) < 32 or max(image.size) / min(image.size) > 8:
        decision.update(status='insufficient_text', elapsed_seconds=time.monotonic() - started)
        return image, decision
    try:
        angle, score, margin = classify_bank_orientation(image, check) if doc_type == 'BANK_CARD' else classify_orientation(image)
    except (ImportError, OSError, ValueError, RuntimeError):
        decision.update(status='unavailable', warning='IMAGE_UPRIGHT_UNAVAILABLE')
    else:
        decision.update(orientation_score=score, orientation_margin=margin)
        if not _confident((angle, score, margin)):
            decision.update(status='uncertain', warning='IMAGE_UPRIGHT_UNCERTAIN')
        else:
            decision['rotation_degrees'] = angle
            upright = apply_correction(image, decision)
            skew, status = estimate_skew(upright, check)
            radians = math.radians(abs(skew))
            expanded_width = math.ceil(upright.width * math.cos(radians) + upright.height * math.sin(radians)) + 2
            expanded_height = math.ceil(upright.height * math.cos(radians) + upright.width * math.sin(radians)) + 2
            if skew and expanded_width * expanded_height > MAX_CORRECTED_PIXELS:
                skew, status = 0., 'skew_uncertain'
            decision.update(deskew_degrees=skew, status=status)
            if status == 'skew_uncertain':
                decision['warning'] = 'IMAGE_DESKEW_UNCERTAIN'
    check()
    corrected = apply_correction(image, decision)
    decision['elapsed_seconds'] = time.monotonic() - started
    return corrected, decision
