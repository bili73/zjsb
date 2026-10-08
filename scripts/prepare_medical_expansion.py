"""Render local medical evaluation inputs; PDF text is never an OCR input."""
import hashlib
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path('F:/dingding/附件_按类型_20260929/体检报告')
OUT = ROOT / 'output/medical-expansion-20260929'
POPPLER = Path('C:/Users/JBS/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    inputs = OUT / 'inputs'
    review = OUT / 'review-images'
    inputs.mkdir(parents=True, exist_ok=True)
    review.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, source in enumerate(sorted(SOURCE.glob('*.pdf')), 1):
        for page, task, kind in [(4, 'ocr', 'conclusion'), (12 if index == 3 else 13, 'table', 'blood')]:
            sample_id = f'medical-{index:02d}-{kind}-p{page:02d}'
            prefix = review / sample_id
            subprocess.run([str(POPPLER), '-f', str(page), '-l', str(page), '-singlefile', '-r', '180', '-png', str(source), str(prefix)], check=True, capture_output=True)
            with Image.open(prefix.with_suffix('.png')) as original:
                image = original.convert('RGB')
                image.thumbnail((1600, 1600))
                target = inputs / f'{sample_id}.png'
                image.save(target)
                size = list(image.size)
            manifest.append(dict(id=sample_id, source=str(source), page=page, image=str(target), task=task, source_sha256=digest(source), input_sha256=digest(target), input_size=size, group=f'medical-case-{index:02d}', document_type='medical_report', input_variant='pdf_render_1600', page_kind=kind))
    source = next(SOURCE.glob('*.jpg'))
    target = inputs / 'medical-01-followup-long-jpg.png'
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((1600, 1600))
        image.save(target)
        size = list(image.size)
    manifest.append(dict(id='medical-01-followup-long-jpg', source=str(source), page=1, image=str(target), task='ocr', source_sha256=digest(source), input_sha256=digest(target), input_size=size, group='medical-case-01', document_type='medical_report', input_variant='long_screenshot_1600', page_kind='followup_urine_ultrasound', relation='same person as medical-01; distinct report date and barcode, not duplicate report'))
    (inputs / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Prepared {len(manifest)} inputs')

if __name__ == '__main__':
    main()
