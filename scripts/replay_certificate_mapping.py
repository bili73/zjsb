"""CPU-only replay of frozen encrypted OCR; persist outcomes, never personal values."""
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.extraction import extract_fields
from ocr_app.storage import Storage
from schema_extraction import score

RUNS = ['dual-extraction-20260930-v1', 'dual-extraction-20260930-v2',
        'dual-extraction-20260930-paddle16-v3']
OUT = ROOT / 'output/field-mapping-replay-20260930-v1/certificates/final'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    rows, summaries, timings, provenance = [], [], [], {}
    extractor_path = ROOT / 'backend/ocr_app/extraction.py'
    extractor_start = extractor_path.read_bytes()
    certificate_source_sha256 = hashlib.sha256(extractor_start.split(b'\nHEADER =', 1)[0]).hexdigest()
    for run in RUNS:
        folder = ROOT / 'output' / run
        watched = [p for p in folder.rglob('*') if p.is_file()]
        before = {str(p.relative_to(folder)): digest(p) for p in watched}
        protocol = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))
        fixture_path = folder / 'private/fixture.enc'
        if digest(fixture_path) != protocol['fixture_sha256']:
            raise RuntimeError('FROZEN_REFERENCE_HASH_MISMATCH')
        storage = Storage(folder / 'private/data')
        fixture = storage.unpack(fixture_path.read_bytes())
        samples = {s['id']: s for s in fixture['samples'] if s['doc_type'] in {'DIPLOMA', 'DEGREE_CERT'}}
        published = {(r['sample_id'], r['method'], r['repeat'], r['field']): r['outcome']
                     for r in read_csv(folder / 'fields.csv')}
        for request in read_csv(folder / 'requests.csv'):
            sid, method, repeat = request['sample_id'], request['method'], request['repeat']
            if sid not in samples or method not in {'glm_rules', 'paddle_rules'}:
                continue
            sample = samples[sid]
            saved = json.loads(storage.read(request['prediction_ref'])) if request['prediction_ref'] else {}
            prediction = saved.get('prediction', {})
            if prediction.get('termination_reason') == 'eos':
                started = time.perf_counter()
                items = extract_fields([dict(text=prediction['text'], page=sample['page'], extraction_method='ocr')], sample['doc_type'])
                extraction_cpu_seconds = time.perf_counter() - started
            else:
                items, extraction_cpu_seconds = [], None
            timings.append(dict(run=run, sample_id=sid, method=method, repeat=int(repeat),
                                extraction_cpu_seconds=extraction_cpu_seconds,
                                timing_scope='extract_fields only; CPU wall time; excludes decrypt/read/score/GPU',
                                extraction_performed=extraction_cpu_seconds is not None,
                                input_sha256=sample['input_sha256']))
            actual = {f['key']: f['value'] for f in items}
            conflicts = {f['key'] for f in items if f.get('review_reason') == 'CONFLICT'}
            old = score(sample['reference'], saved.get('values'), fixture['templates'][sample['doc_type']])
            new = score(sample['reference'], actual, fixture['templates'][sample['doc_type']])
            for previous, current in zip(old, new):
                key = current['field']
                if previous['outcome'] != published[(sid, method, repeat, key)]:
                    raise RuntimeError('PUBLISHED_SCORE_NOT_REPRODUCED')
                rows.append(dict(run=run, sample_id=sid, doc_type=sample['doc_type'], method=method,
                                 repeat=int(repeat), field=key, required=current['required'],
                                 reference_status=current['reference_status'], old_outcome=previous['outcome'],
                                 new_outcome=current['outcome'], new_conflict=key in conflicts,
                                 old_conflict=None, old_conflict_note='not recorded in frozen values',
                                 input_sha256=sample['input_sha256'], prediction_sha256=hashlib.sha256(storage.read(request['prediction_ref'])).hexdigest() if request['prediction_ref'] else None))
        after = {str(p.relative_to(folder)): digest(p) for p in watched}
        if before != after:
            raise RuntimeError('OLD_INPUT_CHANGED')
        provenance[run] = dict(old_inputs_unchanged=True, published_scores_reproduced=True,
                               fixture_sha256=protocol['fixture_sha256'], old_files_sha256=before)
    for run in RUNS:
        for method in ('glm_rules', 'paddle_rules'):
            for scope in ('repeat1', 'all_repeats'):
                selected = [r for r in rows if r['run'] == run and r['method'] == method and (scope == 'all_repeats' or r['repeat'] == 1)]
                entry = dict(run=run, method=method, scope=scope, total_fields=len(selected),
                             present_fields=sum(r['reference_status'] == 'present' for r in selected),
                             absent_fields=sum(r['reference_status'] == 'absent' for r in selected),
                             uncertain_fields=sum(r['reference_status'] == 'uncertain' for r in selected),
                             new_conflicts=sum(r['new_conflict'] for r in selected))
                for version in ('old', 'new'):
                    counts = Counter(r[version + '_outcome'] for r in selected)
                    entry.update({version + '_' + k: counts[k] for k in ('correct', 'missing', 'wrong', 'correct_absence', 'false_positive', 'unscored')})
                summaries.append(entry)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, records in [('fields.csv', rows), ('summary.csv', summaries), ('cpu_timings.csv', timings)]:
        with (OUT / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader(); writer.writerows(records)
    extractor_end = extractor_path.read_bytes()
    if hashlib.sha256(extractor_end.split(b'\nHEADER =', 1)[0]).hexdigest() != certificate_source_sha256:
        raise RuntimeError('CERTIFICATE_CODE_CHANGED_DURING_REPLAY')
    metadata = dict(reference_status='provisional agent-reviewed; not independently double-labelled',
                    policy='same frozen fields and normalization; conflicts abstain and remain missing in present-field score; no old scoring changed',
                    timing_policy='single CPU extraction measurement per frozen inference output; includes UUID generation; no GPU inference; not model throughput',
                    extractor_sha256=hashlib.sha256(extractor_start).hexdigest(),
                    extractor_end_sha256=hashlib.sha256(extractor_end).hexdigest(),
                    certificate_source_sha256=certificate_source_sha256,
                    certificate_code_unchanged_during_replay=True,
                    script_sha256=digest(Path(__file__)), runs=provenance)
    (OUT / 'provenance.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in summaries:
        if row['scope'] == 'repeat1':
            print(json.dumps(row, ensure_ascii=False))


if __name__ == '__main__':
    main()
