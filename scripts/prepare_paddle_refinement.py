"""Targeted fixed-column follow-up; preserve the initial experiment."""
import json
import time
from pathlib import Path
from PIL import Image, ImageOps
from prepare_paddle_ablation_crops import digest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/paddle-ablation-20260929/refinement/inputs'

def main():
    if (OUT / 'manifest.json').exists():
        raise RuntimeError('Refusing to overwrite existing refinement inputs')
    original = next(x for x in json.loads((ROOT / 'output/paddle-ablation-20260929/inputs/crops-manifest.json').read_text(encoding='utf-8')) if x['id'] == 'split--cert-026-p1--r02')
    source = Path(original['source'])
    # Coordinates refer to the original raster after the same EXIF and 90-degree rotation.
    specs = [('r01', 'undergraduate_record', (860, 690, 2860, 1770)),
             ('r02-header', 'college_header', (900, 1710, 2895, 1930)),
             ('r02-left', 'college_left_column', (1400, 1900, 2180, 2730)),
             ('r02-right', 'college_right_column', (2190, 1880, 2895, 2730))]
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with Image.open(source) as raw:
        image = ImageOps.exif_transpose(raw).convert('RGB').rotate(90, expand=True)
        rows = []
        for index, (suffix, name, bbox) in enumerate(specs, 1):
            crop = image.crop(bbox)
            crop.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            sample_id = f'refine--cert-026-p1--{suffix}'
            target = OUT / f'{sample_id}.png'
            crop.save(target)
            rows.append(dict(id=sample_id, parent_id='cert-026-p1', source=str(source), page=1,
                             task='ocr', image=str(target), variant='refine', group='refine',
                             region_index=index, region_name=name, bbox=list(bbox),
                             bbox_coordinate_system=original['bbox_coordinate_system'], input_size=list(crop.size)))
    preparation_seconds = round(time.perf_counter() - started, 6)
    for row in rows:
        row.update(source_sha256=digest(source), input_sha256=digest(Path(row['image'])),
                   rotation_counterclockwise_degrees=90, preparation_seconds=preparation_seconds,
                   region_count=4)
    (OUT / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'regions':len(rows), 'preparation_seconds':preparation_seconds}))

if __name__ == '__main__':
    main()
