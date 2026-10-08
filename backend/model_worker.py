"""Private persistent model process. stdout is a JSON-lines protocol, not a public API."""
import argparse
import base64
import contextlib
import importlib
import io
import json
import math
import os
import sys
import time
from pathlib import Path
from ocr_app.diagnostics import DEFAULT_ROOT, correlation_context, init_diagnostics

ROOT = Path(__file__).resolve().parents[1]
OUT = sys.stdout


def emit(message):
    print(json.dumps(message, ensure_ascii=False), file=OUT, flush=True)


class GenerationGuard:
    """Dependency-free stopping policy, called between decoder steps."""
    def __init__(self, input_length, begin, generation_timeout_seconds=None):
        self.input_length = input_length
        self.begin = begin
        self.timeout = generation_timeout_seconds
        self.reason = None

    def __call__(self, input_ids, scores, **kwargs):
        if self.timeout is not None and time.monotonic() - self.begin >= self.timeout:
            self.reason = 'time_limit'
            return True
        count = input_ids.shape[1] - self.input_length
        if count >= 192 and count % 32 == 0:
            chunk = input_ids[0, -192:].tolist()
            if chunk[:48] == chunk[48:96] == chunk[96:144] == chunk[144:]:
                self.reason = 'repetition_stop'
                return True
        return False


class Engine:
    def __init__(self, model_name, checkpoint_name=None):
        self.name = model_name
        self.checkpoint_name = checkpoint_name or model_name
        allowed = {'glm-ocr'} if model_name == 'glm-ocr' else {'paddleocr-vl', 'paddleocr-vl-1.6'}
        if model_name not in {'glm-ocr', 'paddleocr-vl'} or self.checkpoint_name not in allowed:
            raise ValueError('INVALID_MODEL_CHECKPOINT')
        self.model = self.processor = None
        self.phase = 'loading'

    def load(self):
        os.environ.update(HF_HOME=str(ROOT / '.cache/huggingface'), HF_HUB_OFFLINE='1',
                          TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
        emit({'event': 'phase', 'state': 'loading'})
        begin = time.monotonic()
        import torch
        import psutil
        from PIL import Image, ImageDraw
        from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor
        self.torch = torch
        torch.set_num_threads(4)
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA_UNAVAILABLE')
        checkpoint = ROOT / 'models' / self.checkpoint_name
        options = dict(local_files_only=True, torch_dtype=torch.bfloat16,
                       attn_implementation='sdpa', device_map={'': 0})
        if self.checkpoint_name == 'paddleocr-vl':
            self.model = AutoModelForCausalLM.from_pretrained(checkpoint, trust_remote_code=True, **options).eval()
            module = importlib.import_module(self.model.__class__.__module__)
            original = module.create_causal_mask
            def compatible_mask(*, inputs_embeds, **other):
                return original(input_embeds=inputs_embeds, **other)
            module.create_causal_mask = compatible_mask
            self.processor = AutoProcessor.from_pretrained(checkpoint, trust_remote_code=True, local_files_only=True)
        else:
            self.model = AutoModelForImageTextToText.from_pretrained(checkpoint, **options).eval()
            self.processor = AutoProcessor.from_pretrained(checkpoint, local_files_only=True)
        torch.cuda.synchronize()
        load_seconds = time.monotonic() - begin
        emit({'event': 'phase', 'state': 'warming'})
        self.phase = 'warming'
        warm = Image.new('RGB', (600, 180), 'white')
        ImageDraw.Draw(warm).text((30, 60), 'LOCAL OCR READY 2026', fill='black', font_size=28)
        start = time.monotonic()
        result = self.generate(warm, 'ocr', 48)
        # Releasing allocator cache does not unload weights; limits idle residency overhead.
        torch.cuda.empty_cache()
        return dict(load_seconds=load_seconds, warmup_seconds=time.monotonic() - start,
                    warmup_tokens=result['output_tokens'], gpu_allocated_gib=torch.cuda.memory_allocated() / 2**30,
                    gpu_reserved_gib=torch.cuda.memory_reserved() / 2**30,
                    rss_gib=psutil.Process().memory_info().rss / 2**30,
                    checkpoint=self.checkpoint_name,
                    revision=json.loads((checkpoint / 'download_manifest.json').read_text())['revision'])

    def generate(self, image, task, tokens, generation_timeout_seconds=None):
        from transformers import StoppingCriteria, StoppingCriteriaList
        torch = self.torch
        prompt = 'Table Recognition:' if task == 'table' else ('Text Recognition:' if self.name == 'glm-ocr' else 'OCR:')
        messages = [{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': prompt}]}]
        begin = time.monotonic()
        torch.cuda.reset_peak_memory_stats()
        inputs = self.processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                                     return_dict=True, return_tensors='pt').to('cuda')
        length = inputs['input_ids'].shape[1]
        class Guard(GenerationGuard, StoppingCriteria):
            pass
        guard = Guard(length, begin, generation_timeout_seconds)
        with torch.inference_mode():
            output = self.model.generate(**inputs, max_new_tokens=tokens, do_sample=False, use_cache=True,
                                         stopping_criteria=StoppingCriteriaList([guard]))
        torch.cuda.synchronize()
        generated = output[0, length:]
        result = dict(text=self.processor.decode(generated, skip_special_tokens=True),
                      output_tokens=len(generated), termination_reason=guard.reason or ('token_limit' if len(generated) >= tokens else 'eos'),
                      recognition_seconds=time.monotonic() - begin,
                      gpu_peak_allocated_gib=torch.cuda.max_memory_allocated() / 2**30,
                      gpu_peak_reserved_gib=torch.cuda.max_memory_reserved() / 2**30,
                      max_new_tokens=tokens, generation_timeout_seconds=generation_timeout_seconds)
        del inputs, output, generated
        torch.cuda.empty_cache()
        return result

    def recognize(self, payload):
        from PIL import Image, ImageOps
        self.phase = 'recognize'
        if self.model is None:
            raise RuntimeError('MODEL_NOT_LOADED')
        tokens = int(payload.get('max_new_tokens', 4096))
        if not 1 <= tokens <= 4096 or payload.get('task') not in {'ocr', 'table'}:
            raise ValueError('INVALID_REQUEST')
        soft = payload.get('generation_timeout_seconds')
        if soft is not None and (type(soft) not in (int, float) or not math.isfinite(soft) or soft <= 0):
            raise ValueError('INVALID_REQUEST')
        encoded = payload.get('image_base64')
        if (payload.get('image') is None) == (encoded is None):
            raise ValueError('INVALID_IMAGE_SOURCE')
        if encoded is not None:
            if not isinstance(encoded, str) or len(encoded) > 48 * 1024 * 1024:
                raise ValueError('INVALID_IMAGE_SOURCE')
            source = io.BytesIO(base64.b64decode(encoded, validate=True))
        else:
            source = payload['image']
        with Image.open(source) as original:
            image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((1600, 1600))
        # Preserve existing experimental subclasses that override the three-arg method.
        if soft is None:
            return self.generate(image, payload['task'], tokens)
        return self.generate(image, payload['task'], tokens, generation_timeout_seconds=soft)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', choices=['glm-ocr', 'paddleocr-vl'], required=True)
    ap.add_argument('--checkpoint', choices=['glm-ocr', 'paddleocr-vl', 'paddleocr-vl-1.6'])
    args = ap.parse_args()
    diag = init_diagnostics(Path(os.environ.get('OCR_DIAGNOSTICS_ROOT', str(DEFAULT_ROOT))), 'model',
                            os.environ.get('OCR_DIAGNOSTICS_SESSION'))
    engine = Engine(args.model, args.checkpoint)
    for line in sys.stdin:
        payload = {}
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError('INVALID_REQUEST')
            context = correlation_context(payload.get('context'))
            context.setdefault('request_id', payload.get('id'))
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.load() if payload['op'] == 'load' else engine.recognize(payload)
            emit({'id': payload['id'], 'ok': True, 'result': result})
        except Exception as error:
            torch = getattr(engine, 'torch', None)
            resource = isinstance(error, MemoryError) or (torch is not None and isinstance(error, torch.cuda.OutOfMemoryError))
            if resource:
                code = 'RESOURCE_LIMIT'
            elif isinstance(payload, dict) and payload.get('op') == 'load':
                code = 'MODEL_WARMUP_FAILED' if engine.phase == 'warming' else 'MODEL_LOAD_FAILED'
            elif isinstance(error, (OSError, ValueError)):
                code = 'INPUT_INVALID'
            else:
                code = 'MODEL_PROCESS_EXITED'
            context = correlation_context(payload.get('context')) if isinstance(payload, dict) else {}
            request_id = payload.get('id') if isinstance(payload, dict) else None
            context.setdefault('request_id', request_id)
            error_id = diag.exception('request_failed', error, model=args.model, phase=engine.phase,
                                      error_code=code, **context)
            emit({'id': request_id, 'ok': False, 'error_code': code, 'error_id': error_id})


if __name__ == '__main__':
    main()
