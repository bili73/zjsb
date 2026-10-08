"""Freeze native evidence and all candidate regions for the authorized medical folder."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.documents import decode_pages, png_bytes, region_task, split_regions
from ocr_app.extraction import extract_medical_items
from ocr_app.storage import Storage
from compare_paddle_versions import SOURCES, CHECKPOINTS, norm
from compare_schema_extraction import csv_file, digest, save


def reference_items(items):
    grouped = defaultdict(set)
    for item in items:
        grouped[norm(item['alias'] or item['name'])].add(item['result_raw'])
    return {key: next(iter(values)) for key, values in grouped.items() if len(values) == 1}


def prepare(source, out):
    old = ROOT / 'output/two-model-retest-20260929-152421'
    old_manifest = json.loads((old / 'inputs/manifest.json').read_text(encoding='utf-8'))
    old_refs = json.loads((old / 'references.json').read_text(encoding='utf-8'))['samples']
    visual = {}
    for sample in old_manifest:
        if sample['id'] in {'medical-01-blood-p13', 'medical-02-blood-p13', 'medical-03-blood-p12'}:
            visual[(sample['source_sha256'], sample['page'])] = {
                k.removeprefix('血常规_'): v for k, v in old_refs[sample['id']]['fields'].items() if k.startswith('血常规_')}
    out.mkdir(parents=True, exist_ok=False)
    storage = Storage(out / 'private/data')
    sources, samples, inventory, native = [], [], [], []
    for index, path in enumerate(sorted(p for p in source.rglob('*') if p.is_file()), 1):
        doc_id = f'report-{index:03d}'
        data = path.read_bytes()
        sha = digest(data)
        sources.append(dict(id=doc_id, source_sha256=sha, bytes=len(data), extension=path.suffix.lower(), source_ref=storage.put(data)))
        for page in decode_pages(data):
            page_id = f'{doc_id}-p{page.index:03d}'
            items, limitations = extract_medical_items(page.evidence)
            native_ref = reference_items(items)
            region_boxes = [region for box in page.ocr_boxes for region in split_regions(page.image, box, True)]
            is_blank = page.image.convert('L').getextrema()[0] >= 250
            evidence_ref = storage.put(json.dumps(page.evidence, ensure_ascii=False).encode())
            inventory.append(dict(document_id=doc_id, page=page.index, blank=is_blank,
                                  native_blocks=len(page.evidence), native_chars=sum(len(b['text']) for b in page.evidence),
                                  native_medical_items=len(items), native_unambiguous_references=len(native_ref),
                                  native_limitations=len(limitations), raster_candidates=len(region_boxes),
                                  has_text=any(b['extraction_method'] == 'pdf_text' for b in page.evidence),
                                  native_evidence_ref=evidence_ref))
            gold = visual.get((sha, page.index))
            if gold:
                for key, expected in gold.items():
                    value = native_ref.get(norm(key))
                    native.append(dict(document_id=doc_id, page=page.index, field=key,
                                       reference_basis='visual_provisional', outcome='correct' if value is not None and norm(value) == norm(expected) else 'missing' if value is None else 'wrong'))
            cases = []
            if native_ref:
                cases.append(('forced_native_table', (0, 0, *page.image.size), 'table', native_ref, 'native_pdf_reference'))
            if gold and not native_ref:
                cases.append(('forced_visual_blood', (0, 0, *page.image.size), 'table', {}, 'unscored'))
            for region_index, box in enumerate(region_boxes, 1):
                cases.append((f'raster-{region_index:03d}', box, region_task(page.image, box, True), {}, 'unscored'))
            for case, box, task, reference, basis in cases:
                image = page.image.crop(box)
                image.thumbnail((1600, 1600))
                image_bytes = png_bytes(image)
                sample = dict(id=f'{page_id}-{case}', document_id=doc_id, page=page.index, case=case, task=task,
                              bbox=list(box), input_size=list(image.size), image_ref=storage.put(image_bytes),
                              input_sha256=digest(image_bytes), reference=reference, reference_basis=basis)
                if case.startswith('forced') and gold:
                    sample['visual_reference'] = gold
                samples.append(sample)
            print(json.dumps(dict(document=doc_id, page=page.index, native_items=len(items), raster_regions=len(region_boxes), cases=len(cases))), flush=True)
    encrypted = storage.pack(samples)
    (out / 'private/fixture.enc').write_bytes(encrypted)
    (out / 'private/sources.enc').write_bytes(storage.pack(sources))
    csv_file(out / 'inventory.csv', inventory)
    csv_file(out / 'native_visual_fields.csv', native)
    files = list(dict.fromkeys(SOURCES + ['scripts/prepare_medical_corpus.py', 'backend/ocr_app/documents.py', 'backend/ocr_app/table_format.py']))
    save(out / 'protocol.json', dict(prepared_at=time.time(), fixture_sha256=digest(encrypted),
         sources={p: digest((ROOT / p).read_bytes()) for p in files},
         checkpoints={k: json.loads((ROOT / 'models' / k / 'download_manifest.json').read_text()) for k in CHECKPOINTS},
         repeats=1, max_new_tokens=4096, soft_budget_seconds=45, hard_timeout_seconds=65, match_legacy_pixels=True,
         scoring='Exact whitespace-normalized source-layer result_raw by item alias/name; separate provisional visual blood subset; never native evidence as model accuracy',
         references='Native PDF references and historical provisional visual blood references are separate, not independently human-double-reviewed',
         deduplicate=True, unique_cases=len({(s['input_sha256'], s['task']) for s in samples}),
         documents=[{k: s[k] for k in ['id', 'source_sha256', 'bytes', 'extension']} for s in sources],
         logical_cases=len(samples), pages=len(inventory), case_counts=dict(Counter(s['case'].split('-')[0] for s in samples))))
    print(json.dumps(dict(documents=len(sources), pages=len(inventory), logical_cases=len(samples),
                          unique_cases=len({(s['input_sha256'], s['task']) for s in samples}),
                          native_items=sum(p['native_medical_items'] for p in inventory), native_visual_fields=len(native))), flush=True)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source.resolve(), args.output.resolve())
