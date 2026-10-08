"""Fixed, visually selected CPU crops for the Paddle input ablation."""
import hashlib
import json
import time
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/paddle-ablation-20260929/inputs'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    originals = {}
    for relative in ['output/benchmark-rerun-20260929/inputs/manifest.json', 'output/medical-expansion-20260929/inputs/manifest.json']:
        originals.update({x['id']: x for x in json.loads((ROOT / relative).read_text(encoding='utf-8'))})
    specs = [
        ('cert-020-p1', 0, [('complete_certificate', (0, 880, 1220, 1830), 'ocr')]),
        ('cert-023-p1', 0, [('complete_education_record', (35, 280, 1255, 1970), 'ocr')]),
        ('cert-026-p1', 90, [('undergraduate_record', (860, 690, 2860, 1770), 'ocr'), ('college_record', (900, 1710, 2895, 2900), 'ocr')]),
        ('medical-01-followup-long-jpg', 0, [('urine_report', (70, 290, 1010, 1280), 'table'), ('ultrasound_report', (70, 1840, 1010, 3090), 'ocr'), ('examination_meanings', (70, 3370, 1010, 3735), 'table')]),
        ('medical-01-blood-p13', 0, [('blood_header_and_complete_table', (125, 260, 1340, 1645), 'table')]),
        ('medical-02-blood-p13', 0, [('blood_header_and_complete_table', (125, 260, 1340, 1645), 'table')]),
        ('medical-03-blood-p12', 0, [('blood_header_and_complete_table', (125, 260, 1340, 1645), 'table')]),
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    rows, parents = [], []
    for parent_id, rotation, regions in specs:
        original = originals[parent_id]
        is_pdf = Path(original['source']).suffix.lower() == '.pdf'
        crop_source = ROOT / 'output/medical-expansion-20260929/review-images' / f'{parent_id}.png' if is_pdf else Path(original['source'])
        started = time.perf_counter()
        with Image.open(crop_source) as raw:
            raw_size = list(raw.size)
            exif_orientation = raw.getexif().get(274, 1)
            image = ImageOps.exif_transpose(raw).convert('RGB')
            exif_size = list(image.size)
            if rotation:
                image = image.rotate(rotation, expand=True)
            oriented_size = list(image.size)
            pending = []
            for index, (region_name, box, task) in enumerate(regions, 1):
                assert 0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height
                crop = image.crop(box)
                crop.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                sample_id = f'split--{parent_id}--r{index:02d}'
                target = OUT / f'{sample_id}.png'
                crop.save(target)
                pending.append(dict(id=sample_id, parent_id=parent_id, source=original['source'], page=original['page'], task=task, image=str(target), group='split', variant='split', region_index=index, region_name=region_name, bbox=list(box), bbox_coordinate_system='pixels after EXIF transpose and explicit counterclockwise rotation; left/top inclusive, right/bottom exclusive', input_size=list(crop.size)))
        preparation_seconds = time.perf_counter() - started
        # Hashing and JSON serialization are excluded from preparation timing.
        parent_info = dict(parent_id=parent_id, source=original['source'], crop_source=str(crop_source), source_sha256=digest(Path(original['source'])), crop_source_sha256=digest(crop_source), raw_size=raw_size, source_exif_orientation=exif_orientation, after_exif_size=exif_size, rotation_counterclockwise_degrees=rotation, oriented_source_size=oriented_size, preparation_seconds=round(preparation_seconds, 6), region_count=len(pending), pdf_render_reused=is_pdf, preparation_timing_scope='source raster decode + EXIF + explicit rotation + crop + downscale + PNG writes for all regions; excludes manual selection, hash calculation and PDF rasterization cache generation')
        parents.append(parent_info)
        for row in pending:
            row.update(parent_info)
            row['input_sha256'] = digest(Path(row['image']))
            rows.append(row)
    (OUT / 'crops-manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (OUT / 'crop-preparation.json').write_text(json.dumps({'timing_rule': 'preparation_seconds is per parent, repeated on region rows only for join convenience; sum once per parent, not once per region', 'parents': parents}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'parents': len(parents), 'regions': len(rows), 'preparation_seconds_total': sum(x['preparation_seconds'] for x in parents)}, ensure_ascii=False))

if __name__ == '__main__':
    main()
