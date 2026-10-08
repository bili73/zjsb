"""Prepare and run a serial paired field-extraction experiment. No production writes."""
import argparse
import base64
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.documents import decode_pages, png_bytes
from ocr_app.extraction import extract_fields
from ocr_app.runtime import ModelProcess, RuntimeFailure
from schema_extraction import templates, prompt, output_key, parse_prediction, score


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def csv_file(path, rows):
    if rows:
        with path.open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def prepare(out):
    from PIL import Image, ImageOps
    import fitz
    out.mkdir(parents=True, exist_ok=False)
    storage = Storage(out / 'private/data')
    dictionaries = templates()
    samples = []
    for annotation in json.load(sys.stdin):
        source = Path(annotation.pop('source'))
        original = source.read_bytes()
        if source.suffix.lower() == '.pdf':
            with fitz.open(stream=original, filetype='pdf') as pdf:
                pix = pdf[annotation['page'] - 1].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
        else:
            with Image.open(io.BytesIO(original)) as value:
                image = ImageOps.exif_transpose(value).convert('RGB')
        data = png_bytes(image)
        fields = dictionaries[annotation['doc_type']]
        if set(annotation['reference']) != {f['key'] for f in fields}:
            raise ValueError('REFERENCE_KEYS_MISMATCH')
        for ref in annotation['reference'].values():
            if ref['status'] not in {'present', 'absent', 'uncertain'}:
                raise ValueError('INVALID_REFERENCE_STATUS')
            if ref['status'] == 'present' and ref.get('value') in (None, ''):
                raise ValueError('EMPTY_PRESENT_REFERENCE')
        sample = {**annotation, 'image_ref':storage.put(data), 'input_sha256':digest(data),
                  'source_sha256':digest(original), 'input_size':list(image.size)}
        pdf_source = annotation.pop('native_source', None)
        if pdf_source or source.suffix.lower() == '.pdf':
            started = time.perf_counter()
            iterator = decode_pages(Path(pdf_source).read_bytes() if pdf_source else original)
            try:
                for page in iterator:
                    if page.index == annotation['page']:
                        sample['native_values'] = {f['key']:f['value'] for f in extract_fields(page.evidence, annotation['doc_type'])}
                        break
            finally:
                iterator.close()
            sample['native_page_decode_seconds'] = time.perf_counter() - started
        samples.append(sample)
    private = {'samples':samples, 'templates':dictionaries,
               'prompts':{kind:prompt(fields) for kind,fields in dictionaries.items()},
               'chinese_prompts':{kind:prompt(fields, True) for kind,fields in dictionaries.items()}}
    frozen = storage.pack(private)
    (out / 'private/fixture.enc').write_bytes(frozen)
    save(out / 'protocol.json', dict(version=1, fixture_sha256=digest(frozen),
         spec_sha256=digest((ROOT/'SPEC.md').read_bytes()),
         extractor_sha256=digest((ROOT/'backend/ocr_app/extraction.py').read_bytes()),
         helper_sha256=digest((ROOT/'scripts/schema_extraction.py').read_bytes()),
         worker_sha256=digest((ROOT/'scripts/schema_model_worker.py').read_bytes()),
         max_new_tokens=1024, generation_budget_seconds=45, hard_request_timeout_seconds=65,
         repeats=2, reference_basis='agent visual review before inference; provisional, not independently double-labelled',
         models='single resident GLM; serial calls; no third model',
         prompt_sha256={k:digest(v.encode('utf-8')) for k,v in private['prompts'].items()},
         sample_manifest=[{k:s[k] for k in ('id','doc_type','page','image_ref','input_sha256','input_size')} for s in samples]))
    print(json.dumps({'prepared':len(samples),'reference_fields':sum(len(s['reference']) for s in samples)}), flush=True)


def export(out, records, field_rows):
    csv_file(out/'requests.csv', records)
    csv_file(out/'fields.csv', field_rows)
    groups = []
    for method in sorted({r['method'] for r in records}):
        for kind in ['ALL','DIPLOMA','DEGREE_CERT','MEDICAL_REPORT']:
            rows = [r for r in records if r['method']==method and (kind=='ALL' or r['doc_type']==kind)]
            scored = [r for r in field_rows if r['method']==method and (kind=='ALL' or r['doc_type']==kind)]
            if not rows:
                continue
            counts = Counter(r['outcome'] for r in scored)
            present = sum(counts[k] for k in ('correct','missing','wrong'))
            required = [r for r in scored if r['required'] and r['reference_status']=='present']
            def peak(key):
                measured = [r[key] for r in rows if r[key] is not None]
                return max(measured) if measured else None
            groups.append(dict(method=method, doc_type=kind, requests=len(rows),
                unique_inputs=len({r['sample_id'] for r in rows}), present_fields=present,
                correct=counts['correct'], missing=counts['missing'], wrong=counts['wrong'],
                field_accuracy=counts['correct']/present if present else None,
                missing_rate=counts['missing']/present if present else None,
                wrong_rate=counts['wrong']/present if present else None,
                absent_fields=counts['correct_absence']+counts['false_positive'], false_positives=counts['false_positive'],
                unscored=counts['unscored'], required_present=len(required),
                required_accuracy=sum(r['outcome']=='correct' for r in required)/len(required) if required else None,
                invalid_requests=sum(r['parse_error'] is not None for r in rows),
                total_request_seconds=sum(r['request_seconds'] for r in rows),
                mean_request_seconds=statistics.mean(r['request_seconds'] for r in rows),
                median_request_seconds=statistics.median(r['request_seconds'] for r in rows),
                max_request_seconds=max(r['request_seconds'] for r in rows),
                gpu_peak_allocated_gib=peak('gpu_peak_allocated_gib'),
                gpu_peak_reserved_gib=peak('gpu_peak_reserved_gib'),
                process_rss_peak_gib=peak('process_rss_peak_gib')))
    csv_file(out/'summary.csv', groups)
    save(out/'summary.json', {'scope':'paired image prompt diagnostic; native page CPU baseline separate', 'groups':groups})


def run(out):
    import msvcrt
    import ctypes
    protocol = json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    frozen = (out/'private/fixture.enc').read_bytes()
    if digest(frozen) != protocol['fixture_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    for key,path in [('spec_sha256','SPEC.md'),('extractor_sha256','backend/ocr_app/extraction.py'),
                     ('helper_sha256','scripts/schema_extraction.py'),('worker_sha256','scripts/schema_model_worker.py')]:
        if digest((ROOT/path).read_bytes()) != protocol[key]:
            raise ValueError('BASELINE_CHANGED')
    storage = Storage(out/'private/data')
    fixture = storage.unpack(frozen)
    if (out/'session.json').exists():
        raise ValueError('RUN_ALREADY_STARTED')
    lease = (ROOT/'output/two-model-retest-gpu.lock').open('a+b')
    if lease.tell()==0:
        lease.write(b'1'); lease.flush()
    lease.seek(0)
    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    process = None
    records, field_rows = [], []
    session = dict(status='running', started_at=time.time(), loading=None)
    save(out/'session.json', session)
    sleep_guard = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    def append(sample, method, repeat, values, error, metrics, seconds, prediction_ref=None):
        record = dict(sample_id=sample['id'], doc_type=sample['doc_type'], method=method, repeat=repeat,
                      model_revision=(session.get('loading') or {}).get('revision') if method!='pdf_native_rules' else None,
                      input_sha256=sample['input_sha256'], request_seconds=seconds, parse_error=error,
                      termination_reason=metrics.get('termination_reason'), output_tokens=metrics.get('output_tokens'),
                      recognition_seconds=metrics.get('recognition_seconds'), field_parse_seconds=metrics.get('field_parse_seconds'),
                      gpu_peak_allocated_gib=metrics.get('gpu_peak_allocated_gib'), gpu_peak_reserved_gib=metrics.get('gpu_peak_reserved_gib'),
                      process_rss_peak_gib=metrics.get('process_rss_peak_gib'), host_used_peak_gib=metrics.get('host_used_peak_gib'),
                      host_available_min_gib=metrics.get('host_available_min_gib'), memory_sample_count=metrics.get('memory_sample_count'),
                      prompt_sha256=metrics.get('prompt_sha256'), prediction_ref=prediction_ref)
        records.append(record)
        fields = fixture['templates'][sample['doc_type']]
        field_rows.extend(dict(sample_id=sample['id'], doc_type=sample['doc_type'], method=method, repeat=repeat, **r)
                          for r in score(sample['reference'], values, fields))
        export(out, records, field_rows)
        print(json.dumps(dict(sample=sample['id'], method=method, repeat=repeat, seconds=round(seconds,3),
                              termination=record['termination_reason'], parse_error=error)), flush=True)
    try:
        config = SimpleNamespace(session_dir=out/'technical', model_command=lambda _: [
            str(ROOT/'.venvs/glm-ocr/Scripts/python.exe'), '-u','-X','utf8',str(ROOT/'scripts/schema_model_worker.py')])
        process = ModelProcess('glm_ocr', config, lambda key,state: print(json.dumps({'phase':state}),flush=True))
        started = time.perf_counter()
        session['loading'] = process.call('load',120)
        session['load_request_seconds'] = time.perf_counter()-started
        save(out/'session.json', session)
        print(json.dumps({'phase':'loaded','seconds':session['load_request_seconds']}),flush=True)
        # One schema warmup is separate from formal measurements; never scored.
        first = fixture['samples'][0]
        result = process.call('recognize',65,task='ocr', max_new_tokens=1024,
                image_base64=base64.b64encode(storage.read(first['image_ref'])).decode(), prompt=fixture['prompts'][first['doc_type']])
        reference = storage.put(json.dumps(result,ensure_ascii=False).encode('utf-8'))
        session['schema_warmup'] = {k:v for k,v in result.items() if k!='text'}
        session['schema_warmup']['prediction_ref'] = reference
        save(out/'session.json', session)
        for sample in fixture['samples']:
            data = storage.read(sample['image_ref'])
            if digest(data)!=sample['input_sha256']:
                raise ValueError('INPUT_CHANGED')
            if 'native_values' in sample:
                append(sample,'pdf_native_rules',0,sample['native_values'],None,{},sample['native_page_decode_seconds'])
            for repeat in range(1,protocol['repeats']+1):
                methods = ['text_rules','schema'] if repeat%2 else ['schema','text_rules']
                if 'chinese_prompts' in fixture:
                    methods = ['text_rules','schema','schema_cn'] if repeat%2 else ['schema_cn','schema','text_rules']
                for method in methods:
                    started = time.perf_counter()
                    text_prompt = fixture['prompts'][sample['doc_type']] if method=='schema' else 'Text Recognition:'
                    if method=='schema_cn':
                        text_prompt = fixture['chinese_prompts'][sample['doc_type']]
                    session['in_flight'] = dict(sample_id=sample['id'],method=method,repeat=repeat,started_at=time.time())
                    save(out/'session.json',session)
                    result = process.call('recognize',65,task='ocr',max_new_tokens=1024,
                        image_base64=base64.b64encode(data).decode(),prompt=text_prompt)
                    parse_started = time.perf_counter()
                    if method=='schema_cn':
                        fields = fixture['templates'][sample['doc_type']]
                        values,error = parse_prediction(result['text'],[{**f,'key':output_key(f,True)} for f in fields],result['termination_reason'])
                        if values is not None:
                            values = {f['key']:values[output_key(f,True)] for f in fields}
                    elif method=='schema':
                        values,error = parse_prediction(result['text'],fixture['templates'][sample['doc_type']],result['termination_reason'])
                    elif result['termination_reason']=='eos':
                        evidence = [dict(text=result['text'],page=sample['page'],extraction_method='ocr',bbox=[0,0,1,1])]
                        values = {f['key']:f['value'] for f in extract_fields(evidence,sample['doc_type'])}
                        error = None
                    else:
                        values,error = None,'INCOMPLETE_GENERATION'
                    seconds = time.perf_counter()-started
                    result['field_parse_seconds'] = time.perf_counter()-parse_started
                    result['prompt_sha256'] = digest(text_prompt.encode('utf-8'))
                    prediction_ref = storage.put(json.dumps(dict(prediction=result,values=values),ensure_ascii=False).encode('utf-8'))
                    append(sample,method,repeat,values,error,result,seconds,prediction_ref)
                    session['in_flight'] = None
                    save(out/'session.json',session)
        session['status'] = 'finished'
    except Exception as error:
        session['status'] = 'failed'
        session['error_code'] = error.code if isinstance(error,RuntimeFailure) else type(error).__name__
        # Persist the timed-out measurement; stop instead of reusing a possibly hung process.
        if 'method' in locals() and 'sample' in locals():
            append(sample,method,repeat,None,session['error_code'],{},time.perf_counter()-started)
    finally:
        if process:
            process.close()
            session['owned_process_exited'] = process.poll() is not None
        session['finished_at'] = time.time()
        save(out/'session.json',session)
        if sleep_guard:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lease.close()
    return 0 if session['status']=='finished' else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('--run-dir',type=Path,required=True)
    args = parser.parse_args()
    if args.action=='prepare':
        prepare(args.run_dir.resolve())
        return 0
    return run(args.run_dir.resolve())


if __name__=='__main__':
    raise SystemExit(main())
