"""Frozen, encrypted card/certificate diagnostic. Production is unchanged."""
import argparse
import base64
from collections import Counter
import ctypes
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.runtime import ModelProcess, RuntimeFailure
from compare_schema_extraction import csv_file, digest, save
from schema_extraction import parse_prediction, prompt, score
from dual_extraction import fusion, hint_prompt, paired_metrics, text_values

SOURCES = ['SPEC.md', 'backend/ocr_app/extraction.py', 'backend/model_worker.py',
           'backend/ocr_app/runtime.py', 'backend/ocr_app/winjob.py',
           'scripts/schema_extraction.py', 'scripts/schema_model_worker.py',
           'scripts/run_two_model_retest.py', 'scripts/dual_extraction.py',
           'scripts/dual_model_worker.py', 'scripts/compare_dual_extraction.py',
           'models/glm-ocr/download_manifest.json', 'models/paddleocr-vl/download_manifest.json']


def prepare(out, template_last=False, paddle_checkpoint='paddleocr-vl'):
    previous = ROOT / 'output/schema-extraction-20260930-v2'
    if json.loads((previous / 'validation.json').read_text())['status'] != 'passed':
        raise ValueError('INVALID_SOURCE_REFERENCE')
    protocol = json.loads((previous / 'protocol.json').read_text())
    frozen = (previous / 'private/fixture.enc').read_bytes()
    if digest(frozen) != protocol['fixture_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    old = Storage(previous / 'private/data')
    fixture = old.unpack(frozen)
    out.mkdir(parents=True, exist_ok=False)
    storage = Storage(out / 'private/data')
    samples = []
    for sample in fixture['samples']:
        if sample['doc_type'] not in {'DIPLOMA', 'DEGREE_CERT'}:
            continue
        data = old.read(sample['image_ref'])
        if digest(data) != sample['input_sha256']:
            raise ValueError('INPUT_CHANGED')
        samples.append({**sample, 'image_ref': storage.put(data)})
    bank = ROOT / 'output/bankcard-baseline'
    refs_path = bank / 'review-reference.json'
    refs = {s['id']: s for s in json.loads(refs_path.read_text(encoding='utf-8-sig'))['samples']}
    for sample in json.loads((bank / 'inputs/manifest.json').read_text()):
        data = Path(sample['image']).read_bytes()
        value = refs[sample['id']]['card_number']
        if not isinstance(value, str) or not value.isdigit() or not 16 <= len(value) <= 19:
            raise ValueError('INVALID_BANK_REFERENCE')
        samples.append(dict(id=sample['id'], doc_type='BANK_CARD', page=1,
                            image_ref=storage.put(data), input_sha256=digest(data),
                            input_size=sample['input_size'],
                            reference={'card_number': dict(status='present', value=value)}))
    dictionaries = {k: v for k, v in fixture['templates'].items() if k in {'DIPLOMA', 'DEGREE_CERT'}}
    dictionaries['BANK_CARD'] = [dict(key='card_number', label='卡号', type='string', required=True)]
    prompts = {k: fixture['prompts'][k] for k in ['DIPLOMA', 'DEGREE_CERT']}
    prompts['BANK_CARD'] = ('Read the full printed bank card number from the image. Return only '
                            '{"card_number":""}. Use null if unreadable. Preserve all digits; '
                            'do not guess, correct digits or include expiry/security codes.')
    if template_last:
        for kind in ['DIPLOMA', 'DEGREE_CERT']:
            fields = dictionaries[kind]
            labels = {f['key']: ('学位级别' if f['key'] == 'degree_category' else f['label']) for f in fields}
            example = {f['key']: 0 if f['type'] == 'int' else '' for f in fields}
            prompts[kind] = ('从原图提取信息，严格按下面JSON输出，保留全部键，只输出JSON。没有明确出现或无法确定的字段填null，'
                '不推断学习形式。姓名、学校、专业分别填写。性别用M/F。日期为YYYY-MM-DD，只有年月保留YYYY-MM，'
                '不能补日。学习结束日期、发证日期和授予日期分别判断。学位级别用学士/硕士/博士，学位名称填写完整名称。\n'
                '字段含义：' + json.dumps(labels, ensure_ascii=False) + '\n输出格式：' + json.dumps(example))
        prompts['BANK_CARD'] = ('请按下列JSON格式输出图中信息，只输出JSON。银行卡号按原图逐位抄写，去除分隔空格；'
                                '不猜测或纠正数字。无法确定填null，不输出有效期或安全码。\n输出格式：{"card_number":""}')
    encrypted = storage.pack(dict(samples=samples, templates=dictionaries, prompts=prompts))
    (out / 'private/fixture.enc').write_bytes(encrypted)
    save(out / 'protocol.json', dict(version=1, prepared_at=time.time(),
         fixture_sha256=digest(encrypted), source_fixture_sha256=digest(frozen),
         source_bank_reference_sha256=digest(refs_path.read_bytes()),
         files={p: digest((ROOT / p).read_bytes()) for p in SOURCES +
                ([f'models/{paddle_checkpoint}/download_manifest.json'] if paddle_checkpoint != 'paddleocr-vl' else [])},
         paddle_checkpoint=paddle_checkpoint,
         max_new_tokens=1024, soft_budget_seconds=45, hard_timeout_seconds=65, repeats=2,
         template_last=template_last,
         models='Paddle then GLM; only one resident; all GPU work serial',
         reference_basis='frozen schema v2 visual references; bank fronts visually rechecked before inference; provisional, not independently double-labelled',
         methods=['paddle_rules', 'glm_rules', 'glm_schema', 'paddle_glm_hint', 'merge_preview', 'agreement_only'],
         policy='merge previews prefer nonempty GLM; disagreements remain flagged; agreement-only abstains otherwise; confidence remains null',
         prompt_sha256={k: digest(v.encode()) for k, v in prompts.items()},
         sample_manifest=[{k: s[k] for k in ['id', 'doc_type', 'page', 'input_sha256', 'input_size']} for s in samples],
         reference_counts=dict(Counter(ref['status'] for s in samples for ref in s['reference'].values()))))
    print(json.dumps({'prepared': len(samples)}), flush=True)


def export(out, requests, fields):
    csv_file(out / 'requests.csv', requests)
    csv_file(out / 'fields.csv', fields)
    groups = []
    for method in sorted({r['method'] for r in requests}):
        for kind in ['ALL', 'CERTIFICATES', 'DIPLOMA', 'DEGREE_CERT', 'BANK_CARD']:
            def selected(r):
                return r['method'] == method and (kind == 'ALL' or r['doc_type'] == kind or
                       (kind == 'CERTIFICATES' and r['doc_type'] in {'DIPLOMA', 'DEGREE_CERT'}))
            rows, scored = [r for r in requests if selected(r)], [r for r in fields if selected(r)]
            if not rows:
                continue
            counts = Counter(r['outcome'] for r in scored)
            present = sum(counts[k] for k in ['correct', 'wrong', 'missing'])
            populated = [r for r in scored if r['has_value'] and r['reference_status'] != 'uncertain']
            agreed = [r for r in scored if r['fusion_state'] == 'agreement' and r['reference_status'] != 'uncertain']
            required = [r for r in scored if r['required'] and r['reference_status'] == 'present']
            states = Counter(r['fusion_state'] for r in scored)
            peak = lambda key: max((r[key] for r in rows if r.get(key) is not None), default=None)
            groups.append(dict(method=method, doc_type=kind, requests=len(rows),
                unique_inputs=len({r['sample_id'] for r in rows}), present_fields=present,
                correct=counts['correct'], missing=counts['missing'], wrong=counts['wrong'],
                field_accuracy=counts['correct'] / present if present else None,
                missing_rate=counts['missing'] / present if present else None,
                wrong_rate=counts['wrong'] / present if present else None,
                absent_fields=counts['correct_absence'] + counts['false_positive'],
                false_positives=counts['false_positive'], unscored=counts['unscored'],
                populated_scored=len(populated), populated_precision=counts['correct'] / len(populated) if populated else None,
                required_present=len(required), required_correct=sum(r['outcome'] == 'correct' for r in required),
                agreement_scored=len(agreed), agreement_wrong=sum(r['outcome'] in {'wrong', 'false_positive'} for r in agreed),
                conflicts=states['conflict'], glm_only=states['glm_only'], paddle_only=states['paddle_only'],
                invalid_requests=sum(r['parse_error'] is not None for r in rows),
                mean_request_seconds=statistics.mean(r['request_seconds'] for r in rows),
                median_request_seconds=statistics.median(r['request_seconds'] for r in rows),
                max_request_seconds=max(r['request_seconds'] for r in rows),
                total_request_seconds=sum(r['request_seconds'] for r in rows),
                gpu_peak_allocated_gib=peak('gpu_peak_allocated_gib'),
                gpu_peak_reserved_gib=peak('gpu_peak_reserved_gib'), process_rss_peak_gib=peak('process_rss_peak_gib')))
    csv_file(out / 'summary.csv', groups)
    save(out / 'summary.json', dict(scope='small frozen paired diagnostic; not a population or hardware qualification', groups=groups))


def run(out):
    import msvcrt
    protocol = json.loads((out / 'protocol.json').read_text())
    for path, expected in protocol['files'].items():
        if digest((ROOT / path).read_bytes()) != expected:
            raise ValueError('CODE_CHANGED')
    frozen = (out / 'private/fixture.enc').read_bytes()
    if digest(frozen) != protocol['fixture_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    if (out / 'session.json').exists():
        raise ValueError('RUN_ALREADY_STARTED')
    storage = Storage(out / 'private/data')
    fixture = storage.unpack(frozen)
    lease = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
    if lease.tell() == 0:
        lease.write(b'1'); lease.flush()
    lease.seek(0)
    msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
    guard = bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
    session = dict(status='running', started_at=time.time(), sleep_prevention_active=guard, models=[])
    save(out / 'session.json', session)
    requests, fields, paddle = [], [], {}

    def append(sample, method, repeat, values, error, metrics, prediction_ref=None, states=None):
        row = dict(sample_id=sample['id'], doc_type=sample['doc_type'], method=method, repeat=repeat,
                   input_sha256=sample['input_sha256'], parse_error=error, prediction_ref=prediction_ref,
                   confidence=None, human_review_required=True,
                   **{k: metrics.get(k) for k in ['request_seconds', 'recognition_seconds', 'field_parse_seconds',
                        'output_tokens', 'termination_reason', 'gpu_peak_allocated_gib', 'gpu_peak_reserved_gib',
                        'process_rss_peak_gib', 'host_used_peak_gib', 'host_available_min_gib',
                        'memory_sample_count', 'paddle_stage_seconds', 'glm_stage_seconds', 'fusion_seconds', 'prompt_sha256']})
        requests.append(row)
        for result in score(sample['reference'], values, fixture['templates'][sample['doc_type']]):
            fields.append(dict(sample_id=sample['id'], doc_type=sample['doc_type'], method=method, repeat=repeat,
                               **result, has_value=(values or {}).get(result['field']) not in (None, ''),
                               fusion_state=(states or {}).get(result['field'], 'single_model'),
                               confidence=None, human_review_required=True))
        export(out, requests, fields)
        print(json.dumps(dict(sample=sample['id'], method=method, repeat=repeat,
                              seconds=round(row['request_seconds'], 3), parse_error=error,
                              termination=row['termination_reason'])), flush=True)

    def recognize(process, sample, method, repeat, text_prompt):
        data = storage.read(sample['image_ref'])
        if digest(data) != sample['input_sha256']:
            raise ValueError('INPUT_CHANGED')
        session['in_flight'] = dict(sample_id=sample['id'], method=method, repeat=repeat, started_at=time.time())
        save(out / 'session.json', session)
        start = time.perf_counter()
        try:
            result = process.call('recognize', protocol['hard_timeout_seconds'], task='ocr',
                                  max_new_tokens=protocol['max_new_tokens'], prompt=text_prompt,
                                  image_base64=base64.b64encode(data).decode())
        except RuntimeFailure as error:
            append(sample, method, repeat, None, error.code, {'request_seconds': time.perf_counter() - start})
            raise
        parsed = time.perf_counter()
        if method in {'paddle_rules', 'glm_rules'}:
            values = text_values(result['text'], sample['doc_type'], sample['page']) if result['termination_reason'] == 'eos' else None
            error = None if values is not None else 'INCOMPLETE_GENERATION'
        else:
            values, error = parse_prediction(result['text'], fixture['templates'][sample['doc_type']], result['termination_reason'])
        result.update(field_parse_seconds=time.perf_counter() - parsed,
                      request_seconds=time.perf_counter() - start, prompt_sha256=digest(text_prompt.encode()))
        reference = storage.put(json.dumps(dict(prediction=result, values=values), ensure_ascii=False).encode())
        session['in_flight'] = None
        save(out / 'session.json', session)
        return values, error, result, reference

    try:
        for model in ['paddleocr-vl', 'glm-ocr']:
            checkpoint = protocol.get('paddle_checkpoint', model) if model == 'paddleocr-vl' else model
            config = SimpleNamespace(session_dir=out / 'technical' / model, model_command=lambda _: [
                str(ROOT / '.venvs' / checkpoint / 'Scripts/python.exe'), '-u', '-X', 'utf8',
                str(ROOT / 'scripts/dual_model_worker.py'), '--model', model, '--checkpoint', checkpoint])
            process = ModelProcess(model.replace('-', '_'), config, lambda key, state: print(json.dumps(dict(model=key, phase=state)), flush=True))
            model_session = dict(model=model, started_at=time.time())
            session['models'].append(model_session)
            try:
                start = time.perf_counter()
                model_session['loading'] = process.call('load', 120)
                model_session['load_request_seconds'] = time.perf_counter() - start
                save(out / 'session.json', session)
                print(json.dumps(dict(model=model, phase='loaded', seconds=model_session['load_request_seconds'])), flush=True)
                for sample in fixture['samples']:
                    for repeat in range(1, protocol['repeats'] + 1):
                        if model == 'paddleocr-vl':
                            result = recognize(process, sample, 'paddle_rules', repeat, 'OCR:')
                            paddle[(sample['id'], repeat)] = result
                            append(sample, 'paddle_rules', repeat, *result[:3], result[3])
                            continue
                        direct = None
                        first = paddle[(sample['id'], repeat)]
                        base = fixture['prompts'][sample['doc_type']]
                        methods = ['glm_rules', 'glm_schema', 'paddle_glm_hint']
                        if repeat == 2:
                            methods.reverse()
                        for method in methods:
                            text_prompt = 'Text Recognition:' if method == 'glm_rules' else base
                            if method == 'paddle_glm_hint':
                                text_prompt = hint_prompt(base, first[2]['text'] if first[1] is None else '', protocol.get('template_last', False))
                            values, error, metrics, ref = recognize(process, sample, method, repeat, text_prompt)
                            if method == 'paddle_glm_hint':
                                metrics.update(paired_metrics(first[2], metrics))
                            append(sample, method, repeat, values, error, metrics, ref)
                            if method == 'glm_schema':
                                direct = (values, error, metrics, ref)
                        for method in ['merge_preview', 'agreement_only']:
                            start = time.perf_counter()
                            values, states = fusion(direct[0], first[0], fixture['templates'][sample['doc_type']], method == 'agreement_only')
                            metrics = paired_metrics(first[2], direct[2], time.perf_counter() - start)
                            metrics['termination_reason'] = 'derived'
                            ref = storage.put(json.dumps(dict(values=values, states=states, glm_ref=direct[3], paddle_ref=first[3]), ensure_ascii=False).encode())
                            append(sample, method, repeat, values, direct[1] or first[1], metrics, ref, states)
            finally:
                process.close()
                model_session.update(owned_process_exited=process.poll() is not None, finished_at=time.time())
                save(out / 'session.json', session)
        session['status'] = 'finished'
    except Exception as error:
        session.update(status='failed', error_code=error.code if isinstance(error, RuntimeFailure) else type(error).__name__)
    finally:
        session['finished_at'] = time.time()
        save(out / 'session.json', session)
        if guard:
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lease.close()
    return 0 if session['status'] == 'finished' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--template-last', action='store_true', help='Prepare an exploratory schema-last prompt variant')
    parser.add_argument('--paddle-checkpoint', choices=['paddleocr-vl', 'paddleocr-vl-1.6'], default='paddleocr-vl')
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.run_dir.resolve(), args.template_last, args.paddle_checkpoint)
    else:
        raise SystemExit(run(args.run_dir.resolve()))
