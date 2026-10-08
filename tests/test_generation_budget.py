"""CPU-only soft generation and post-load deadline regressions."""
import base64
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from ocr_app.config import RuntimeConfig
from ocr_app.runtime import ModelManager, RuntimeFailure
import model_worker
import runtime_worker
from ocr_app.diagnostics import safe_context


class Tokens:
    def __init__(self, values):
        self.values = values
        self.shape = (1, len(values))
    def __getitem__(self, index):
        return Tokens(self.values[index[1]])
    def tolist(self):
        return self.values
    def __len__(self):
        return len(self.values)


class GenerationBudgetTests(unittest.TestCase):
    def test_guard_budget_includes_preprocessing_and_short_generation(self):
        guard = model_worker.GenerationGuard(5, 10., 20.)
        with patch('model_worker.time.monotonic', return_value=30.):
            self.assertTrue(guard(Tokens([1] * 6), None))
        self.assertEqual(guard.reason, 'time_limit')

    def test_guard_exact_repeat_and_no_default_time_limit(self):
        guard = model_worker.GenerationGuard(0, 0., None)
        self.assertFalse(guard(Tokens(list(range(192))), None))
        self.assertTrue(guard(Tokens(list(range(48)) * 4), None))
        self.assertEqual(guard.reason, 'repetition_stop')

    def test_engine_soft_return_then_eos_without_reload(self):
        clock = [0.]
        preprocessing = [21.]
        class Inputs(dict):
            def to(self, device):
                return self
        def prepare(*args, **kwargs):
            clock[0] += preprocessing[0]
            return Inputs(input_ids=Tokens([7, 8]))
        def generate(**kwargs):
            guard = kwargs['stopping_criteria'][0]
            stopped = guard(Tokens([7, 8, 9]), None)
            self.assertEqual(stopped, preprocessing[0] >= 20)
            return Tokens([7, 8, 9])
        engine = model_worker.Engine('glm-ocr')
        engine.model = SimpleNamespace(generate=generate)
        engine.processor = SimpleNamespace(apply_chat_template=prepare, decode=lambda *a, **kw: 'available')
        engine.torch = SimpleNamespace(inference_mode=contextlib.nullcontext, cuda=Mock())
        engine.torch.cuda.max_memory_allocated.return_value = 0
        engine.torch.cuda.max_memory_reserved.return_value = 0
        fake_transformers = SimpleNamespace(StoppingCriteria=type('StoppingCriteria', (), {}), StoppingCriteriaList=list)
        with patch.dict(sys.modules, transformers=fake_transformers), patch('model_worker.time.monotonic', side_effect=lambda: clock[0]):
            result = engine.generate(None, 'ocr', 1234, 20)
            self.assertEqual(result['termination_reason'], 'time_limit')
            self.assertEqual(result['text'], 'available')
            self.assertEqual(result['generation_timeout_seconds'], 20)
            preprocessing[0] = 0.
            self.assertEqual(engine.generate(None, 'ocr', 1234, 20)['termination_reason'], 'eos')

    def test_engine_image_protocol_budget_forwarding_and_validation(self):
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'white').save(image, format='PNG')
        payload = dict(image_base64=base64.b64encode(image.getvalue()).decode(), task='ocr',
                       max_new_tokens=1234, generation_timeout_seconds=20)
        engine = model_worker.Engine('glm-ocr')
        engine.model = object()
        engine.generate = Mock(return_value={})
        engine.recognize(payload)
        self.assertEqual(engine.generate.call_args.args[1:], ('ocr', 1234))
        self.assertEqual(engine.generate.call_args.kwargs, {'generation_timeout_seconds': 20})
        for invalid in (0, -1, float('nan'), float('inf'), True, '20'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                engine.recognize({**payload, 'generation_timeout_seconds': invalid})

    def test_business_chain_forwards_actual_budget_and_refreshes_shared_revisions(self):
        manager = Mock()
        manager.metrics = [dict(operation='load', model='glm_ocr', revision='first')]
        def recognize(model, **kwargs):
            manager.metrics.append(dict(operation='load', model=model, revision='new'))
            return dict(text='partial', termination_reason='time_limit', max_new_tokens=1234,
                        generation_timeout_seconds=5.)
        manager.recognize.side_effect = recognize
        store = Mock()
        store.storage.read.return_value = b'input'
        store.storage.unpack.return_value = {}
        def process(content, doc_type, **kwargs):
            revisions = kwargs['model_revisions']
            self.assertEqual(revisions, {'glm_ocr': 'first'})
            prediction = kwargs['recognize']('paddleocr_vl', 'encoded', 'table', 25,
                max_new_tokens=1234, generation_timeout_seconds=20, context={'page': 2})
            self.assertEqual(revisions, {'glm_ocr': 'first', 'paddleocr_vl': 'new'})
            kwargs['record_attempt'](dict(model='paddleocr_vl', task='table', prediction=prediction,
                generation_timeout_seconds=20, max_new_tokens=1234))
            return {'status': 'NEED_REVIEW'}
        task = dict(id='task', run_id='run', input_ref='input', options_enc=None, doc_type='MEDICAL_REPORT')
        with patch('ocr_app.pipeline.process_document', side_effect=process):
            runtime_worker._process_task(store, manager, task, Mock())
        forwarded = manager.recognize.call_args.kwargs
        self.assertEqual(forwarded['generation_timeout_seconds'], 20)
        self.assertEqual(forwarded['max_new_tokens'], 1234)
        self.assertEqual(forwarded['context']['page'], 2)
        record = store.attempt.call_args.args[1]
        self.assertEqual(record['generation_timeout_seconds'], 5)
        self.assertEqual(record['max_new_tokens'], 1234)
        self.assertEqual(record['model_revision'], 'new')

    def test_soft_termination_and_actual_budgets_survive_safe_logs(self):
        data = dict(termination_reason='time_limit', generation_timeout_seconds=20., max_new_tokens=1234)
        self.assertEqual(safe_context(data), data)

    def make_manager(self, elapsed=0., failure=None):
        clock = [100.]
        calls = []
        def factory(key, config, phase):
            client = Mock()
            client.poll.return_value = None
            def call(operation, timeout, **payload):
                calls.append((operation, timeout, payload, client))
                if operation == 'load':
                    clock[0] += elapsed
                    return {'revision': 'frozen-revision'}
                if failure:
                    raise RuntimeFailure(failure)
                return {'text': 'partial', 'termination_reason': 'time_limit'}
            client.call.side_effect = call
            return client
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        manager = ModelManager(RuntimeConfig(Path(temp.name), 'single_resident'), factory=factory)
        self.addCleanup(manager.close)
        return manager, calls, clock

    def test_cold_load_is_not_subject_to_soft_limit_and_worker_reused(self):
        manager, calls, clock = self.make_manager(elapsed=55.)
        with patch('ocr_app.runtime.time.monotonic', side_effect=lambda: clock[0]):
            for _ in range(2):
                result = manager.recognize('paddleocr_vl', 'unused', timeout=180,
                    max_new_tokens=1234, generation_timeout_seconds=20)
                self.assertEqual(result['termination_reason'], 'time_limit')
        self.assertEqual([c[0] for c in calls], ['load', 'recognize', 'recognize'])
        self.assertGreater(calls[0][1], 55)
        self.assertEqual(calls[1][1], 30)
        self.assertEqual(calls[1][2]['generation_timeout_seconds'], 20)
        self.assertEqual(calls[1][2]['max_new_tokens'], 1234)
        self.assertEqual(manager.snapshot()['models']['paddleocr_vl'], 'ready')
        calls[1][3].close.assert_not_called()

    def test_remaining_budget_clips_soft_and_hard_after_load(self):
        manager, calls, clock = self.make_manager(elapsed=165.)
        with patch('ocr_app.runtime.time.monotonic', side_effect=lambda: clock[0]):
            manager.recognize('paddleocr_vl', 'unused', timeout=180, generation_timeout_seconds=20)
        self.assertEqual(calls[-1][1], 15)
        self.assertEqual(calls[-1][2]['generation_timeout_seconds'], 5)

    def test_default_certificate_budget_unchanged(self):
        manager, calls, clock = self.make_manager()
        with patch('ocr_app.runtime.time.monotonic', side_effect=lambda: clock[0]):
            manager.recognize('glm_ocr', 'unused', timeout=80)
        self.assertEqual(calls[-1][1], 80)
        self.assertNotIn('generation_timeout_seconds', calls[-1][2])

    def test_hard_timeout_still_closes_worker(self):
        manager, calls, clock = self.make_manager(failure='MODEL_REQUEST_TIMEOUT')
        with self.assertRaises(RuntimeFailure):
            manager.recognize('paddleocr_vl', 'unused', generation_timeout_seconds=20)
        calls[-1][3].close.assert_called_once()
        self.assertNotIn('paddleocr_vl', manager.clients)

    def test_invalid_soft_budgets_rejected_before_spawn(self):
        for invalid in (0, -1, float('nan'), float('inf'), True, '20'):
            manager, calls, _ = self.make_manager()
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                manager.recognize('glm_ocr', 'unused', generation_timeout_seconds=invalid)
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
