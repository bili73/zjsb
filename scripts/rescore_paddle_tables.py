"""Offline adapter rescore; frozen inference records and private values stay unchanged."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.extraction import extract_medical_items
from compare_schema_extraction import csv_file, digest, save
from compare_paddle_versions import norm


def rescore(source, out):
    out.mkdir(parents=True, exist_ok=False)
    storage = Storage(source / 'private/data')
    frozen = (source / 'private/fixture.enc').read_bytes()
    protocol = json.loads((source / 'protocol.json').read_text())
    if digest(frozen) != protocol['fixture_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    samples = {s['id']: s for s in storage.unpack(frozen)}
    with (source / 'requests.csv').open(encoding='utf-8-sig', newline='') as stream:
        original = list(csv.DictReader(stream))
    provenance = dict(source=str(source.relative_to(ROOT)), fixture_sha256=digest(frozen),
                      requests_sha256=digest((source / 'requests.csv').read_bytes()),
                      decoder_sha256=digest((ROOT / 'backend/ocr_app/table_format.py').read_bytes()),
                      extractor_sha256=digest((ROOT / 'backend/ocr_app/extraction.py').read_bytes()),
                      scorer_sha256=digest(Path(__file__).read_bytes()),
                      inference_rerun=False, score_scope=protocol['scoring'], predictions={})
    fields, requests = [], []
    for row in original:
        blob = storage.path(row['prediction_ref']).read_bytes()
        provenance['predictions'][row['prediction_ref']] = digest(blob)
        private = json.loads(storage.read(row['prediction_ref']))
        begin = time.perf_counter()
        items, limitations = extract_medical_items([dict(text=private['result']['text'], page=1, extraction_method='ocr', bbox=[0, 0, 1, 1])])
        candidates = defaultdict(list)
        for item in items:
            for key in {item['name'], item['alias']} - {None, ''}:
                candidates[norm(key)].append(item['result_raw'])
        for key, expected in samples[row['sample_id']]['reference'].items():
            options = set(candidates.get(norm(key), []))
            predicted = next(iter(options)) if len(options) == 1 else None
            outcome = 'correct' if predicted is not None and norm(predicted) == norm(expected) else 'missing' if predicted is None else 'wrong'
            fields.append(dict(checkpoint=row['checkpoint'], sample_id=row['sample_id'], repeat=int(row['repeat']), field=key,
                               outcome=outcome, has_value=predicted is not None, complete_generation=row['termination_reason'] == 'eos'))
        requests.append(dict(checkpoint=row['checkpoint'], sample_id=row['sample_id'], repeat=int(row['repeat']),
                             input_sha256=row['input_sha256'], termination_reason=row['termination_reason'],
                             original_request_seconds=float(row['request_seconds']),
                             offline_decode_score_seconds=time.perf_counter() - begin,
                             parsed_items=len(items), limitation_count=len(limitations),
                             gpu_peak_allocated_gib=float(row['gpu_peak_allocated_gib']),
                             process_rss_peak_gib=float(row['process_rss_peak_gib']), prediction_ref=row['prediction_ref']))
    summary = []
    for checkpoint in sorted({r['checkpoint'] for r in requests}):
        rows = [r for r in requests if r['checkpoint'] == checkpoint]
        scored = [f for f in fields if f['checkpoint'] == checkpoint]
        correct = sum(f['outcome'] == 'correct' for f in scored)
        summary.append(dict(checkpoint=checkpoint, requests=len(rows), fields=len(scored), correct=correct,
                            accuracy=correct / len(scored), missing=sum(f['outcome'] == 'missing' for f in scored),
                            wrong=sum(f['outcome'] == 'wrong' for f in scored), mean_original_request_seconds=statistics.mean(r['original_request_seconds'] for r in rows),
                            mean_offline_decode_score_seconds=statistics.mean(r['offline_decode_score_seconds'] for r in rows),
                            parsed_items=sum(r['parsed_items'] for r in rows),
                            gpu_peak_allocated_gib=max(r['gpu_peak_allocated_gib'] for r in rows),
                            process_rss_peak_gib=max(r['process_rss_peak_gib'] for r in rows)))
    save(out / 'protocol.json', provenance)
    csv_file(out / 'requests.csv', requests)
    csv_file(out / 'fields.csv', fields)
    csv_file(out / 'summary.csv', summary)
    print(json.dumps(summary))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    rescore(args.source.resolve(), args.output.resolve())
