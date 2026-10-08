"""Bounded serial diagnostic worker in each model's existing environment."""
import argparse
import contextlib
import importlib.metadata
import json
import sys

from schema_model_worker import ProbeEngine, MemorySampler, emit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['glm-ocr', 'paddleocr-vl'], required=True)
    parser.add_argument('--checkpoint', choices=['glm-ocr', 'paddleocr-vl', 'paddleocr-vl-1.6'])
    parser.add_argument('--match-legacy-pixels', action='store_true')
    args = parser.parse_args()
    if args.match_legacy_pixels and (args.model != 'paddleocr-vl' or args.checkpoint != 'paddleocr-vl-1.6'):
        parser.error('Legacy pixel matching is only for the new Paddle diagnostic')
    engine = ProbeEngine(args.model, args.checkpoint)
    default = 'OCR:' if args.model == 'paddleocr-vl' else 'Text Recognition:'
    engine.field_prompt = default
    monitor = MemorySampler()
    try:
        for line in sys.stdin:
            payload = json.loads(line)
            monitor.reset()
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    if payload['op'] == 'load':
                        result = engine.load()
                        if args.match_legacy_pixels:
                            engine.processor.image_processor.size = {'shortest_edge': 147384, 'longest_edge': 2822400}
                        result['formal_image_processor_size'] = dict(engine.processor.image_processor.size)
                        result['warmup_image_profile'] = 'checkpoint_default'
                        result.update(gpu=engine.torch.cuda.get_device_name(),
                                      gpu_total_gib=engine.torch.cuda.get_device_properties(0).total_memory / 2**30,
                                      host_total_gib=monitor.psutil.virtual_memory().total / 2**30,
                                      python=sys.version,
                                      versions={k: importlib.metadata.version(k) for k in
                                                ['torch', 'transformers', 'accelerate', 'psutil', 'Pillow']})
                    else:
                        engine.field_prompt = payload.get('prompt', 'Table Recognition:' if payload.get('task') == 'table' else default)
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
