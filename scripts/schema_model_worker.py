"""Experimental JSON prompt worker in the existing isolated GLM environment."""
import contextlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from model_worker import Engine, emit
from run_two_model_retest import MemorySampler


class ProbeEngine(Engine):
    field_prompt = None
    budget = 45

    def generate(self, image, task, tokens):
        from transformers import StoppingCriteria, StoppingCriteriaList
        torch = self.torch
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image},
                    {'type': 'text', 'text': self.field_prompt or 'Text Recognition:'}]}]
        start = time.perf_counter()
        torch.cuda.reset_peak_memory_stats()
        inputs = self.processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                                    return_dict=True, return_tensors='pt').to('cuda')
        length = inputs['input_ids'].shape[1]
        engine = self
        class Guard(StoppingCriteria):
            reason = None
            def __call__(self, input_ids, scores, **kwargs):
                count = input_ids.shape[1] - length
                if time.perf_counter() - start >= engine.budget:
                    self.reason = 'generation_timeout'
                    return True
                if count >= 192 and count % 32 == 0:
                    tail = input_ids[0, -192:].tolist()
                    if tail[:48] == tail[48:96] == tail[96:144] == tail[144:]:
                        self.reason = 'repetition_stop'
                        return True
                return False
        guard = Guard()
        with torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=tokens, do_sample=False, use_cache=True,
                                         stopping_criteria=StoppingCriteriaList([guard]))
        torch.cuda.synchronize()
        generated = output[0, length:]
        result = dict(text=self.processor.decode(generated, skip_special_tokens=True), output_tokens=len(generated),
                      termination_reason=guard.reason or ('token_limit' if len(generated) >= tokens else 'eos'),
                      recognition_seconds=time.perf_counter() - start,
                      gpu_peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30,
                      gpu_peak_reserved_gib=torch.cuda.max_memory_reserved() / 2**30)
        del inputs, output, generated
        torch.cuda.empty_cache()
        return result


def main():
    engine = ProbeEngine('glm-ocr')
    monitor = MemorySampler()
    try:
        for line in sys.stdin:
            payload = json.loads(line)
            monitor.reset()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    if payload['op'] == 'load':
                        result = engine.load()
                        result['gpu'] = engine.torch.cuda.get_device_name()
                        result['host_total_gib'] = monitor.psutil.virtual_memory().total / 2**30
                    else:
                        engine.field_prompt = payload.get('prompt')
                        result = engine.recognize(payload)
                result.update(monitor.snapshot())
                emit(dict(id=payload['id'], ok=True, result=result))
            except Exception as error:
                emit(dict(id=payload['id'], ok=False, error_code='PROBE_' + type(error).__name__.upper()))
    finally:
        monitor.stop.set()
        monitor.thread.join(timeout=2)


if __name__ == '__main__':
    main()
