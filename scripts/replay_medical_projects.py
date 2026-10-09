"""Native-only project-catalogue observations; no recognition model requests."""
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.documents import decode_pages
from ocr_app.extraction import extract_result
from ocr_app.storage import Storage
import fitz


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalize(value):
    return re.sub(r'(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])', '', value).strip()


def main():
    out = ROOT / 'output/medical-project-catalogue-20261008-v1/native-replay'
    out.mkdir(parents=True, exist_ok=False)
    vault = Storage(out / 'private/data')
    baseline_path = ROOT / 'output/medical-subsection-label-replay-20261008-v1/summary.json'
    baseline = {c['input_sha256']: c for c in json.loads(baseline_path.read_text(encoding='utf-8'))['cases']}
    baseline_hash = digest(baseline_path.read_bytes())
    paths = sorted(Path(r'F:\dingding\附件_按类型_20260929\体检报告').glob('*.pdf'))
    assert len(paths) == 3
    cases = []
    code_files = [ROOT/'backend/ocr_app/extraction.py', ROOT/'backend/ocr_app/doc_profiles.py', Path(__file__).resolve()]
    hashes = {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in code_files}
    for index, path in enumerate(paths, 1):
        raw = path.read_bytes()
        evidence, pending, pages = [], 0, 0
        for page in decode_pages(raw):
            evidence.extend(page.evidence)
            pending += len(page.ocr_boxes)
            pages += 1
            page.image.close()
        result = extract_result(evidence, 'MEDICAL_REPORT', complete=False)
        field = next(f for f in result['fields'] if f['key'] == 'exam_projects')
        observed = field['value'].split('；') if field['value'] else []
        reference, reference_pages = [], []
        with fitz.open(stream=raw, filetype='pdf') as document:
            for page in document:
                if not any(re.fullmatch(r'[一二三四五六七八九十0-9]+[、.．]本次体检项目意义', re.sub(r'\s+', '', line)) for line in page.get_text().splitlines()):
                    continue
                for table in page.find_tables().tables:
                    rows = table.extract()
                    headers = [re.sub(r'\s+', '', c or '') for c in rows[0]]
                    if headers.count('项目') == 1 and '临床意义' in headers:
                        column = headers.index('项目')
                        reference.extend(normalize(row[column]) for row in rows[1:] if row[column])
                        reference_pages.append(page.number + 1)
        known = {(b['page'],b['region_id']) for b in evidence}
        sources = field.get('sources', [])
        sources_valid = all((s.get('page'),s.get('region_id')) in known and s.get('bbox_kind') == 'cell'
                            and len(s.get('bbox', [])) == 4 and s['bbox'][0] < s['bbox'][2] and s['bbox'][1] < s['bbox'][3]
                            and all(0 <= x <= 1 for x in s['bbox']) for s in sources)
        assert observed == list(dict.fromkeys(reference))
        assert sources_valid and len(sources) == len(reference)
        assert not {'report_no','institution','report_date','package_name'} & {f['key'] for f in result['fields']}
        assert digest(path.read_bytes()) == digest(raw)
        identifier = f'medical-{index:03}'
        (out/'private'/f'{identifier}.enc').write_bytes(vault.pack(result))
        summary = result['report_summary']
        previous = baseline[digest(raw)]
        assert len(result['items']) == previous['items_after']
        assert (summary['declared_count'], len(summary['findings']), summary['count_check']) == (
            previous['summary_declared'], previous['summary_findings'], previous['summary_count_check'])
        assert all(not item.get('abnormal_exclusion_reason') for item in result['abnormal_summary'])
        cases.append(dict(case_id=identifier, input_sha256=digest(raw), page_count=pages,
                          projects=observed, project_count=len(observed), reference_count=len(reference),
                          reference_pages=reference_pages, matches_native_table_column=True,
                          cell_sources=len(sources), cell_sources_valid=sources_valid,
                          detection_items=len(result['items']), findings=len(summary['findings']),
                          declared_count=summary['declared_count'], count_check=summary['count_check'],
                          excluded_measurement_rows=sum(bool(i.get('abnormal_exclusion_reason')) for i in result['items']),
                          bmi_rows=sum('体重指数' in i['name'] or i['name'].strip().upper() == 'BMI' for i in result['items']),
                          detection_and_report_counts_unchanged=True,
                          pending_graphic_regions=pending, model_calls=0, source_unchanged=True))
        print(json.dumps({k:cases[-1][k] for k in ['case_id','project_count','cell_sources_valid','pending_graphic_regions']}, ensure_ascii=False))
    assert hashes == {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in code_files}
    assert digest(baseline_path.read_bytes()) == baseline_hash
    report = dict(status='passed', scope='Native extraction observations versus directly read project cells; not independently labelled accuracy or model timing.',
                  cases=cases, model_calls=0, code_hashes=hashes, code_unchanged=True, baseline_sha256=baseline_hash, baseline_unchanged=True)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        keys = ['case_id','project_count','reference_count','cell_sources','cell_sources_valid','detection_items','findings','declared_count','count_check','excluded_measurement_rows','bmi_rows','detection_and_report_counts_unchanged','pending_graphic_regions','model_calls','source_unchanged']
        writer = csv.DictWriter(stream,fieldnames=keys)
        writer.writeheader()
        writer.writerows({k:case[k] for k in keys} for case in cases)


if __name__ == '__main__':
    main()
