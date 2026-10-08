"""Local diagnostic only: publish field names and counts, never private OCR values."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.extraction import plain
from schema_extraction import normalize
from compare_schema_extraction import save

LITERAL_FIELDS = {'name', 'school_name', 'major', 'certificate_no', 'education_level', 'degree_name', 'study_mode'}


def fold(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value)))


def audit(out):
    storage = Storage(out / 'private/data')
    fixture = storage.unpack((out / 'private/fixture.enc').read_bytes())
    samples = {s['id']: s for s in fixture['samples']}
    with (out / 'requests.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    counts, failures = {}, []
    for row in rows:
        sample = samples[row['sample_id']]
        if row['repeat'] != '1' or sample['doc_type'] == 'BANK_CARD':
            continue
        prediction = json.loads(storage.read(row['prediction_ref']))
        if row['method'] in {'glm_rules', 'paddle_rules'}:
            text = fold(plain(prediction['prediction']['text']))
            values = prediction['values'] or {}
            counters = counts.setdefault(row['method'], Counter())
            for key, reference in sample['reference'].items():
                if key not in LITERAL_FIELDS or reference['status'] != 'present':
                    continue
                counters['checked_literal_fields'] += 1
                present = fold(reference['value']) in text
                counters['reference_literally_visible'] += present
                correct = normalize(key, values.get(key)) == normalize(key, reference['value'])
                counters['visible_but_not_correctly_mapped'] += present and not correct
        if row['method'] in {'glm_schema', 'paddle_glm_hint'} and row['parse_error']:
            detail = dict(sample_id=row['sample_id'], method=row['method'], parse_error=row['parse_error'])
            try:
                text = prediction['prediction']['text'].strip()
                if text.startswith('```') and text.endswith('```'):
                    text = re.sub(r'^```(?:json)?\s*', '', text).removesuffix('```').strip()
                raw = json.loads(text)
                keys = {f['key']: f for f in fixture['templates'][sample['doc_type']]}
                if isinstance(raw, dict):
                    detail.update(missing_keys=sorted(set(keys) - set(raw)),
                                  missing_required_keys=sorted(k for k, f in keys.items() if f['required'] and k not in raw),
                                  extra_key_count=len(set(raw) - set(keys)))
            except (ValueError, TypeError):
                detail['syntactically_invalid'] = True
            failures.append(detail)
    result = dict(literal_diagnostic=counts, schema_contract_failures=failures,
                  warning='Literal presence is not field correctness; date/semantic mapping is excluded. Partial JSON is inspected, not silently accepted or rescored.')
    save(out / 'extraction-audit.json', result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir', type=Path)
    audit(parser.parse_args().run_dir)
