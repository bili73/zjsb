"""Install the pinned official CPU orientation model; recognition never downloads it."""
import hashlib
from pathlib import Path
import sys
import urllib.request
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.image_preprocessing import MODEL_PATH, MODEL_SHA256, MODEL_URL


def main():
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if MODEL_PATH.exists():
        if hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest() != MODEL_SHA256:
            raise SystemExit('Existing orientation model hash mismatch; preserve and inspect it before replacing.')
        print('Orientation model already verified.')
        return
    temporary = MODEL_PATH.with_name(MODEL_PATH.name + '.' + uuid4().hex + '.download')
    try:
        # Each installer owns its own partial file and never deletes another's.
        with temporary.open('xb') as target, urllib.request.urlopen(MODEL_URL, timeout=30) as response:
            digest = hashlib.sha256()
            size = 0
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > 7_000_000:
                    raise ValueError('ORIENTATION_MODEL_SIZE_MISMATCH')
                target.write(chunk)
                digest.update(chunk)
        if size != 6_788_069 or digest.hexdigest() != MODEL_SHA256:
            raise ValueError('ORIENTATION_MODEL_HASH_MISMATCH')
        temporary.replace(MODEL_PATH)
        print('Official orientation model installed and SHA256 verified (6,788,069 bytes).')
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
