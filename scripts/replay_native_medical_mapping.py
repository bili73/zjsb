"""CPU-only, anonymous replay of frozen medical evidence; never runs OCR.

Run only after the implementation is frozen. References remain in the existing
encrypted corpus. Expected counts are post-extraction assertions, not inputs to
decode_pages or extract_result. Existing outputs are never overwritten.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import re
import sys
from time import perf_counter_ns

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / 'output/field-mapping-replay-20260930-v1/native'
CODE = ('backend/ocr_app/documents.py', 'backend/ocr_app/extraction.py',
        'backend/ocr_app/table_format.py', 'backend/ocr_app/storage.py',
        'scripts/replay_native_medical_mapping.py')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def norm(value):
    return re.sub(r'\s+', '', str(value))


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def valid_box(box):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in box)
            and box[0] < box[2] and box[1] < box[3])


def source_valid(origin, blocks, *, row=False):
    """Validate source linkage and row geometry without emitting source text."""
    matching = blocks.get((origin.get('page'), origin.get('region_id')), [])
    if len(matching) != 1 or origin.get('extraction_method') != 'pdf_text':
        return False
    if not valid_box(origin.get('bbox')):
        return False
    if not row:
        return True
    box = origin['bbox']
    return origin.get('bbox_kind') == 'row' and any(
        valid_box(meta.get('bbox')) and all(abs(a - b) <= 1e-6 for a, b in zip(box, meta['bbox']))
        for meta in matching[0].get('table_rows', []))


def run(args):
    if args.out.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    corpus = args.corpus.resolve()
    artifacts = {'protocol': corpus / 'protocol.json',
                 'fixture': corpus / 'private/fixture.enc',
                 'sources': corpus / 'private/sources.enc',
                 'summary_expectations': REPLAY / 'title_lookup.json'}
    hashes_before = {key: file_hash(path) for key, path in artifacts.items()}
    code_before = {name: file_hash(ROOT / name) for name in CODE}
    protocol = json.loads(artifacts['protocol'].read_text(encoding='utf-8'))
    if hashes_before['fixture'] != protocol['fixture_sha256']:
        raise ValueError('FROZEN_FIXTURE_HASH_MISMATCH')
    if not (corpus / 'private/secrets/data-key.dpapi').is_file():
        raise ValueError('EXISTING_CORPUS_KEY_REQUIRED')
    if not args.source_dir.is_dir():
        raise ValueError('ORIGINAL_SOURCE_DIRECTORY_UNAVAILABLE')
    originals = {path: file_hash(path) for path in args.source_dir.iterdir()
                 if path.is_file() and path.suffix.lower() == '.pdf'}
    sys.path.insert(0, str(ROOT / 'backend'))
    from ocr_app.documents import decode_pages
    from ocr_app.extraction import extract_result
    from ocr_app.storage import Storage

    storage = Storage(corpus / 'private/data')
    sources = storage.unpack(artifacts['sources'].read_bytes())
    fixture = storage.unpack(artifacts['fixture'].read_bytes())
    expected_summaries = json.loads(artifacts['summary_expectations'].read_text(encoding='utf-8'))['title_matches']
    expected_by_id = {entry['document_id']: entry for entry in expected_summaries}
    frozen_docs = {entry['id']: entry for entry in protocol['documents']}
    pdfs = [entry for entry in sources if entry['extension'].lower() == '.pdf']
    if len(pdfs) != 3 or {s['id'] for s in pdfs} != set(expected_by_id):
        raise ValueError('FROZEN_DOCUMENT_SET_MISMATCH')
    native_rows, summary_rows, source_rows, field_rows = [], [], [], []
    for entry in sorted(pdfs, key=lambda s: s['id']):
        document_id = entry['id']
        frozen = frozen_docs[document_id]
        data = storage.read(entry['source_ref'])
        sha = digest(data)
        snapshot_verified = (sha == entry['source_sha256'] == frozen['source_sha256']
                             and len(data) == entry['bytes'] == frozen['bytes'])
        physical_matches = [p for p, h in originals.items() if h == sha]
        if not snapshot_verified or not physical_matches:
            raise ValueError('ORIGINAL_SOURCE_HASH_MISMATCH')

        # Keep only lightweight native evidence. Page images are closed each iteration.
        evidence, page_count, pending_regions = [], 0, 0
        decode_started = perf_counter_ns()
        for page in decode_pages(data):
            evidence.extend(page.evidence)
            page_count += 1
            pending_regions += len(page.ocr_boxes)
            page.image.close()
        decode_ms = (perf_counter_ns() - decode_started) / 1_000_000
        mapping_started = perf_counter_ns()
        result = extract_result(evidence, 'MEDICAL_REPORT', complete=False)
        mapping_ms = (perf_counter_ns() - mapping_started) / 1_000_000

        # Reference lookup happens only after production extraction has finished.
        refs = [sample for sample in fixture if sample['document_id'] == document_id
                and sample.get('visual_reference')]
        if not refs or any((r['page'], r['visual_reference']) !=
                           (refs[0]['page'], refs[0]['visual_reference']) for r in refs):
            raise ValueError('FROZEN_REFERENCE_AMBIGUOUS')
        blood_page, reference = refs[0]['page'], refs[0]['visual_reference']
        expected = {norm(key): value for key, value in reference.items()}
        if len(expected) != len(reference):
            raise ValueError('FROZEN_REFERENCE_KEYS_COLLIDE')
        actual = defaultdict(list)
        blocks = defaultdict(list)
        for block in evidence:
            blocks[(block['page'], block['region_id'])].append(block)
        blood_items = [item for item in result['items'] if item['source']['page'] == blood_page]
        for item in blood_items:
            actual[norm(item.get('alias') or item['name'])].append(item)
        counts = dict(correct=0, missing=0, wrong=0, ambiguous=0)
        for key, target in expected.items():
            candidates = actual.get(key, [])
            outcome = ('missing' if not candidates else 'ambiguous' if len(candidates) != 1
                       else 'correct' if norm(candidates[0]['result_raw']) == norm(target) else 'wrong')
            counts[outcome] += 1
            # Keys are frozen test labels, never predicted free-form patient text.
            field_rows.append(dict(document_id=document_id, page=blood_page, field=key, outcome=outcome))
        extra = sum(len(items) for key, items in actual.items() if key not in expected)
        native_rows.append(dict(document_id=document_id, page_count=page_count, blood_page=blood_page,
            mapped_items=len(blood_items), reference_fields=len(expected), **counts, extra_items=extra,
            row_sources_valid=sum(source_valid(item['source'], blocks, row=True) for item in blood_items),
            native_evidence_count=len(evidence), pending_ocr_regions=pending_regions,
            all_native_mapped_items=len(result['items']), decode_ms=round(decode_ms, 3),
            field_mapping_ms=round(mapping_ms, 3)))

        summary = result['report_summary']
        previous = expected_by_id[document_id]
        findings = summary['findings']
        origins = [origin for finding in findings for origin in finding['sources']]
        expected_count = int(previous['declared_count'])
        row_checks = [bool(finding['sources']) and all(source_valid(s, blocks, row=True)
                      for s in finding['sources']) for finding in findings]
        title_page_found = any(s.get('page') == previous['page'] for s in summary['sources'])
        summary_rows.append(dict(document_id=document_id, declared_count=summary['declared_count'],
            existing_expected_count=expected_count, findings_count=len(findings), scope=summary['scope'],
            count_check=summary['count_check'], source_page_min=min((s['page'] for s in origins), default=None),
            source_page_max=max((s['page'] for s in origins), default=None),
            row_sources_valid=sum(row_checks), all_sources_resolve=all(
                source_valid(s, blocks) for s in [*summary['sources'], *origins]),
            existing_title_page_found=title_page_found,
            reported_numbers_consecutive=[f['reported_number'] for f in findings] ==
                [str(n) for n in range(1, len(findings) + 1)],
            declared_count_matches_existing=summary['declared_count'] == expected_count,
            findings_count_matches_existing=len(findings) == expected_count))
        source_rows.append(dict(document_id=document_id, source_sha256=sha, bytes=len(data),
            frozen_snapshot_verified=snapshot_verified, original_source_matches=len(physical_matches),
            original_source_unchanged=all(file_hash(p) == sha for p in physical_matches)))
        print(json.dumps(dict(document_id=document_id, pages=page_count, reference_fields=len(expected),
                              **counts, summary_findings=len(findings), decode_ms=round(decode_ms, 3),
                              field_mapping_ms=round(mapping_ms, 3))), flush=True)

    unchanged = all(file_hash(path) == hashes_before[key] for key, path in artifacts.items())
    code_after = {name: file_hash(ROOT / name) for name in CODE}
    checks = dict(reference_fields_72=sum(r['reference_fields'] for r in native_rows) == 72,
        all_blood_values_correct=all(r['correct'] == r['reference_fields'] and r['extra_items'] == 0
                                    and r['row_sources_valid'] == r['mapped_items'] for r in native_rows),
        all_summary_checks=all(r['declared_count_matches_existing'] and r['findings_count_matches_existing']
            and r['scope'] == 'follow_up_required' and r['count_check'] == 'match'
            and r['row_sources_valid'] == r['findings_count'] and r['all_sources_resolve']
            and r['reported_numbers_consecutive'] and r['existing_title_page_found'] for r in summary_rows),
        original_sources_unchanged=all(r['original_source_unchanged'] for r in source_rows),
        frozen_artifacts_unchanged=unchanged, implementation_unchanged_during_run=code_before == code_after)
    provenance = dict(created_at=datetime.now(timezone.utc).isoformat(), python=platform.python_version(),
        packages={name: version(name) for name in ('PyMuPDF', 'Pillow', 'beautifulsoup4', 'pillow-heif')},
        code_sha256_before=code_before, code_sha256_after=code_after, artifact_sha256=hashes_before,
        sources=source_rows, checks=checks, passed=all(checks.values()),
        scoring='Whitespace-only normalization of frozen provisional visual result_raw by alias/name; duplicate labels are ambiguous, never selected by expected value.',
        reference_status='Existing encrypted visual references; not independently human-double-reviewed. No new truth created.',
        summary_expectations='Existing anonymous title_lookup.json declarations; post-extraction verification only.',
        timing='perf_counter_ns; decode includes CPU rendering/native extraction; mapping is full-report extract_result. Excludes input decryption, hashing, scoring and output writes.',
        coverage='Native-only replay, complete=False. OCR candidates remain pending. These results do not establish whole-report or model accuracy.')
    args.out.mkdir(parents=True, exist_ok=False)
    write_csv(args.out / 'native_replay.csv', native_rows)
    write_csv(args.out / 'summary.csv', summary_rows)
    write_csv(args.out / 'field_checks.csv', field_rows)
    write_json(args.out / 'provenance.json', provenance)
    write_json(args.out / 'replay.json', dict(native=native_rows, summary=summary_rows,
                                            checks=checks, passed=all(checks.values())))
    return 0 if all(checks.values()) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=ROOT / 'output/medical-corpus-20260930-v2')
    parser.add_argument('--out', type=Path, default=REPLAY / 'final')
    parser.add_argument('--source-dir', type=Path, default=Path('F:/dingding/附件_按类型_20260929/体检报告'))
    try:
        sys.exit(run(parser.parse_args()))
    except Exception as exc:
        # Avoid tracebacks or raw exception strings containing patient filenames/text.
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'[A-Z_]+', str(exc)) else 'REPLAY_FAILED'
        print(json.dumps(dict(status='failed', error_type=type(exc).__name__, code=code)), file=sys.stderr)
        sys.exit(1)
