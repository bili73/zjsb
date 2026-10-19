"""Isolated Windows CUDA batch qualification; never enables production batching."""
import argparse
import gc
import importlib.metadata
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


class RowStops:
    """Track each row once; one row stopping never stops the entire batch."""
    def __init__(self, count, eos, limit, *, cancel_after=None, deadlines=None):
        self.eos, self.limit = set(eos), limit
        self.cancel_after, self.deadlines = cancel_after or {}, deadlines or {}
        self.reasons, self.lengths, self.finished_at = [None] * count, [None] * count, [None] * count
        self.first_token_at = None

    def step(self, length, last_tokens, elapsed, tails=None):
        if self.first_token_at is None:
            self.first_token_at = elapsed
        for row, token in enumerate(last_tokens):
            if self.reasons[row] is not None:
                continue
            reason = None
            if token in self.eos:
                reason = 'eos'
            elif row in self.cancel_after and length >= self.cancel_after[row]:
                reason = 'cancelled'
            elif elapsed >= self.deadlines.get(row, 40):
                reason = 'time_limit'
            elif tails and len(tails[row]) == 192 and tails[row][:48] == tails[row][48:96] == tails[row][96:144] == tails[row][144:]:
                reason = 'repetition_stop'
            elif length >= self.limit:
                reason = 'token_limit'
            if reason:
                self.reasons[row], self.lengths[row], self.finished_at[row] = reason, length, elapsed
        return [reason is not None for reason in self.reasons]


def generate_batch(engine, images, task, *, cancel_after=None, deadlines=None):
    from transformers import StoppingCriteria, StoppingCriteriaList
    torch = engine.torch
    tokenizer = engine.processor.tokenizer
    tokenizer.padding_side = 'left'
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    prompt = 'Table Recognition:' if task == 'table' else ('Text Recognition:' if engine.name == 'glm-ocr' else 'OCR:')
    conversations = [[{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': prompt}]}]
                     for image in images]
    torch.cuda.synchronize()
    began = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    inputs = engine.processor.apply_chat_template(conversations, tokenize=True, add_generation_prompt=True,
        padding=True, return_dict=True, return_tensors='pt').to('cuda')
    if inputs['input_ids'].shape[0] != len(images):
        raise ValueError('PROCESSOR_BATCH_MISMATCH')
    prompt_length = inputs['input_ids'].shape[1]
    eos = engine.model.generation_config.eos_token_id or tokenizer.eos_token_id
    stops = RowStops(len(images), eos if isinstance(eos, list) else [eos], 512,
                     cancel_after=cancel_after, deadlines=deadlines)

    class Guard(StoppingCriteria):
        def __call__(self, ids, scores, **kwargs):
            length = ids.shape[1] - prompt_length
            tails = ids[:, -192:].tolist() if length >= 192 and length % 32 == 0 else None
            mask = stops.step(length, ids[:, -1].tolist(), time.perf_counter() - began, tails)
            return torch.tensor(mask, dtype=torch.bool, device=ids.device)

    with torch.inference_mode():
        output = engine.model.generate(**inputs, max_new_tokens=512, do_sample=False, use_cache=True,
            pad_token_id=tokenizer.pad_token_id, stopping_criteria=StoppingCriteriaList([Guard()]))
    if output.shape[0] != len(images):
        raise ValueError('OUTPUT_BATCH_MISMATCH')
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - began
    results = []
    for row in range(len(images)):
        length = stops.lengths[row] or output.shape[1] - prompt_length
        tokens = output[row, prompt_length:prompt_length + length]
        results.append(dict(text=engine.processor.decode(tokens, skip_special_tokens=True), output_tokens=length,
            termination_reason=stops.reasons[row] or 'token_limit',
            first_token_seconds=stops.first_token_at, finish_seconds=stops.finished_at[row] or elapsed))
    metrics = dict(batch_seconds=elapsed, gpu_peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30,
                   gpu_peak_reserved_gib=torch.cuda.max_memory_reserved() / 2**30)
    del inputs, output
    torch.cuda.empty_cache()
    return results, metrics


def samples(out):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 27)
    result = []
    for task in ['ocr', 'table']:
        for index in range(4):
            image = Image.new('RGB', (920, 640 + 20 * index), 'white')
            draw = ImageDraw.Draw(image)
            lines = ([f'BATCH TEST ONLY {index + 1}', '毕业证书（合成测试）', f'姓名：TEST-{index + 1}',
                      '学校：合成示例大学', '专业：计算机科学', '毕业日期：2026年6月30日'] if task == 'ocr' else
                     [f'合成检验表 TEST-{index + 1}', '项目        结果        单位        参考范围',
                      '谷丙转氨酶   18          U/L          0-40', '葡萄糖        4.8         mmol/L       3.9-6.1',
                      '血红蛋白      142         g/L          120-160', '仅为调度测试数据，无临床含义'])
            for line, value in enumerate(lines):
                draw.text((35, 30 + line * 83), value, font=font, fill='black')
            path = out / f'synthetic-{task}-{index + 1}.png'
            image.save(path)
            result.append(dict(id=f'{task}-{index + 1}', task=task, image=image))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', choices=['glm-ocr', 'paddleocr-vl'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / 'output'):
        parser.error('output must be inside this repository output directory')
    out.mkdir(parents=True, exist_ok=False)
    import msvcrt
    with (ROOT / 'output/two-model-retest-gpu.lock').open('a+b') as lease:
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        sys.path.insert(0, str(ROOT / 'backend'))
        from model_worker import Engine
        engine = Engine(args.model)
        report = dict(model=args.model, sizes=[1, 2, 4], batches=[], row_stop_probes=[],
            backend={name: importlib.metadata.version(name) for name in ['torch', 'transformers']},
            dtype='bfloat16', max_new_tokens=512, soft_budget_seconds=40,
            passed=False, scope='synthetic CUDA throughput and consistency; not business accuracy or Mac qualification')

        def save():
            (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

        try:
            report['startup'] = engine.load()
            report['vision_isolation'] = engine.vision_isolation
            cases = samples(out)
            reference = {}
            report['rounds'] = {str(size): 'NOT_RUN' for size in [1, 2, 4]}
            for size in [1, 2, 4]:
                report['rounds'][str(size)] = 'RUNNING'
                round_start = time.perf_counter()
                for task in ['ocr', 'table']:
                    group = [case for case in cases if case['task'] == task]
                    for offset in range(0, len(group), size):
                        chunk = group[offset:offset + size]
                        submitted = time.perf_counter() - round_start
                        record = dict(batch_size=size, task=task, case_ids=[case['id'] for case in chunk], status='started')
                        report['batches'].append(record)
                        save()
                        try:
                            outputs, metrics = generate_batch(engine, [case['image'] for case in chunk], task)
                            for case, value in zip(chunk, outputs):
                                if size == 1:
                                    reference[case['id']] = ''.join(value['text'].split())
                                value['matches_size1'] = ''.join(value['text'].split()) == reference.get(case['id'])
                                value['complete_from_round_start_seconds'] = submitted + value['finish_seconds']
                            record.update(status='completed', results=outputs, **metrics)
                        except Exception as error:
                            record.update(status='failed', error_type=type(error).__name__)
                            save()
                            raise
                        save()
                print(json.dumps(dict(event='round_complete', model=args.model, batch_size=size,
                                      seconds=time.perf_counter() - round_start)), flush=True)
                report['rounds'][str(size)] = 'COMPLETED'
            for kind, options in [('cancel', dict(cancel_after={0: 8})), ('deadline', dict(deadlines={0: 0.001}))]:
                outputs, metrics = generate_batch(engine, [case['image'] for case in cases[:2]], 'ocr', **options)
                expected = 'cancelled' if kind == 'cancel' else 'time_limit'
                passed = outputs[0]['termination_reason'] == expected and outputs[1]['termination_reason'] == 'eos'
                report['row_stop_probes'].append(dict(kind=kind, passed=passed, results=outputs, **metrics))
                save()
            report['all_outputs_match_size1'] = all(row['matches_size1'] for batch in report['batches'] for row in batch.get('results', []))
            report['passed'] = report['all_outputs_match_size1'] and all(batch['status'] == 'completed' and all(row['termination_reason'] == 'eos'
                for row in batch['results']) for batch in report['batches']) and all(p['passed'] for p in report['row_stop_probes'])
        except Exception as error:
            for size, state in report.get('rounds', {}).items():
                if state == 'RUNNING':
                    report['rounds'][size] = 'FAILED'
            report['failure_type'] = type(error).__name__
            raise
        finally:
            save()
            gc.collect()
        if not report['passed']:
            raise SystemExit(2)


if __name__ == '__main__':
    main()
