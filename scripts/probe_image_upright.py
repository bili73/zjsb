"""CPU-only certificate/card preparation probe; keep originals and encrypted OCR inputs."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import statistics
import sys
from collections import Counter

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.image_preprocessing import prepare_image, MODEL_SHA256, UPRIGHT_DOCUMENT_TYPES
from ocr_app.storage import Storage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    script_hash = digest(Path(__file__).read_bytes())
    implementation_hash = digest((ROOT/'backend/ocr_app/image_preprocessing.py').read_bytes())
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True, help='Explicit task IDs and manually checked base rotations; never select by model confidence.')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    root = Path(manifest['data_root']).resolve()
    assert (root / 'tasks.sqlite3').exists() and (root.parent / 'secrets/data-key.dpapi').exists()
    args.out.mkdir(parents=True, exist_ok=False)
    source = Storage(root)
    output = Storage(args.out / 'private/data')
    connection = sqlite3.connect((root / 'tasks.sqlite3').as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    rows, provenance, references = [], [], []
    for index, sample in enumerate(manifest['samples'], 1):
        task = connection.execute('SELECT * FROM tasks WHERE id=?', (sample['task_id'],)).fetchone()
        assert task['doc_type'] in UPRIGHT_DOCUMENT_TYPES
        content = source.read(task['input_ref'])
        assert not content.lstrip().startswith(b'%PDF-')
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(content))).convert('RGB')
        base = sample['base_rotation_ccw']
        if base:
            image = image.transpose({90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}[base])
        identity = f'sample-{index:02}'
        provenance.append(dict(sample=identity, input_sha256=digest(content), reference=task['input_ref'],
                               result_cipher_sha256=digest(task['result_enc'] or b''), task_id=task['id'], revision=task['revision']))
        for rotation in [0,90,180,270,-5,5]:
            if rotation in {0,90,180,270}:
                varied = image if not rotation else image.transpose({90:Image.Transpose.ROTATE_90,180:Image.Transpose.ROTATE_180,270:Image.Transpose.ROTATE_270}[rotation])
                expected = (-rotation) % 360
            else:
                varied = image.rotate(rotation, resample=Image.Resampling.BICUBIC, expand=True, fillcolor='white')
                expected = 0
            corrected, decision = prepare_image(varied, doc_type=task['doc_type'])
            case = f'{identity}-{rotation:+04}'
            row = dict(case=case, sample=identity, doc_type=task['doc_type'], input_sha256=digest(content),
                       added_rotation_ccw=rotation, expected_quarter_turn_ccw=expected,
                       orientation_correct=decision['rotation_degrees']==expected,
                       added_skew_error_degrees=abs(decision['deskew_degrees']+rotation) if rotation in {-5,5} else None,
                       **decision)
            rows.append(row)
            variants = {}
            for label, pixels in [('before',varied),('after',corrected)]:
                pixels = pixels.copy()
                pixels.thumbnail((1600,1600))
                stream=io.BytesIO();pixels.save(stream,format='PNG')
                variants[label]=output.put(stream.getvalue())
            references.append(dict(case=case, sample=identity, doc_type=task['doc_type'], rotation=rotation, **variants))
        print(f'CPU preparation: {index}/{len(manifest["samples"])} sources checked',flush=True)
    for sample in provenance:
        current=connection.execute('SELECT revision,result_enc FROM tasks WHERE id=?',(sample['task_id'],)).fetchone()
        assert (current['revision'],digest(current['result_enc'] or b''))==(sample['revision'],sample['result_cipher_sha256'])
        assert digest(source.read(sample['reference']))==sample['input_sha256']
    timed=[row['elapsed_seconds'] for row in rows]
    summary=dict(model_sha256=MODEL_SHA256, sources=len(provenance), cases=len(rows),
        quarter_turn_cases=sum(r['added_rotation_ccw'] in {0,90,180,270} for r in rows),
        quarter_turn_correct=sum(r['orientation_correct'] for r in rows if r['added_rotation_ccw'] in {0,90,180,270}),
        rotated_cases_abstained=sum(r['status']=='uncertain' and r['expected_quarter_turn_ccw']!=0 for r in rows),
        rotated_cases_wrong_nonzero=sum(r['added_rotation_ccw'] in {90,180,270} and r['rotation_degrees'] not in {0,r['expected_quarter_turn_ccw']} for r in rows),
        unrotated_controls_wrong_quarter_turn=sum(r['rotation_degrees']!=0 for r in rows if r['added_rotation_ccw']==0),
        skew_cases=sum(r['added_skew_error_degrees'] is not None for r in rows),
        skew_within_one_degree=sum(r['added_skew_error_degrees'] is not None and r['added_skew_error_degrees']<=1 for r in rows),
        statuses=dict(Counter(r['status'] for r in rows)),mean_prepare_seconds=statistics.mean(timed),
        median_prepare_seconds=statistics.median(timed),max_prepare_seconds=max(timed),
        first_prepare_seconds=timed[0],warm_mean_prepare_seconds=statistics.mean(timed[1:]),
        recognition_model_calls=0, originals_and_saved_results_unchanged=True,
        limitations='Known synthetic rotations of manually oriented existing photos; repeated inputs are not independent documents. Small-angle errors are relative to approximately level photographed originals, not independently measured physical baselines. CPU preparation times include orientation and pixel correction, exclude decode/EXIF/PNG/storage/OCR. No OCR accuracy or Mac performance claim.',
        script_sha256=script_hash, implementation_sha256=implementation_hash)
    summary['by_doc_type'] = {}
    for kind in sorted({row['doc_type'] for row in rows}):
        subset = [row for row in rows if row['doc_type'] == kind]
        turned = [row for row in subset if row['added_rotation_ccw'] in {90,180,270}]
        controls = [row for row in subset if row['added_rotation_ccw'] == 0]
        summary['by_doc_type'][kind] = dict(
            sources=len({row['sample'] for row in subset}), cases=len(subset),
            rotated_cases=len(turned), rotated_correct=sum(row['orientation_correct'] for row in turned),
            rotated_abstained=sum(row['rotation_degrees']==0 for row in turned),
            rotated_wrong_nonzero=sum(row['rotation_degrees'] not in {0,row['expected_quarter_turn_ccw']} for row in turned),
            unrotated_controls_wrong_quarter_turn=sum(row['rotation_degrees']!=0 for row in controls),
            unrotated_controls_deskewed=sum(row['deskew_degrees']!=0 for row in controls),
            mean_prepare_seconds=statistics.mean(row['elapsed_seconds'] for row in subset))
    assert digest(Path(__file__).read_bytes())==script_hash
    assert digest((ROOT/'backend/ocr_app/image_preprocessing.py').read_bytes())==implementation_hash
    with (args.out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.out/'private/fixtures.enc').write_bytes(output.pack(dict(provenance=provenance,references=references)))
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
