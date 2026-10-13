"""One bounded CPU OCR call. PNG in, compact JSON out; never log recognized text."""
from io import BytesIO
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import numpy as np
    from PIL import Image
    from ocr_app.document_classification import _engine

    data = sys.stdin.buffer.read(8_000_001)
    if not data or len(data) > 8_000_000:
        raise ValueError('invalid crop')
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > 2_000_000:
            raise ValueError('invalid crop')
        pixels = np.asarray(image.convert('RGB'))
    result = _engine()(pixels)
    texts = list(result.txts) if result.txts is not None else []
    scores = [float(score) for score in result.scores] if result.scores is not None else []
    text = '\n'.join(texts).strip()
    if len(text) > 4096:
        raise ValueError('output too long')
    sys.stdout.buffer.write(json.dumps(dict(text=text, confidence=min(scores, default=0.)),
                                       ensure_ascii=True, allow_nan=False).encode('ascii'))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit(1) from None
