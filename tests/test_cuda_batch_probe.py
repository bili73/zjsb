"""Batch stopping semantics require no CUDA, Transformers or model weights."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from probe_cuda_batches import RowStops


class RowStopTests(unittest.TestCase):
    def test_cancelled_row_does_not_stop_or_rewrite_peer(self):
        guard = RowStops(2, [2], 10, cancel_after={0: 2})
        self.assertEqual(guard.step(1, [4, 5], 0.1), [False, False])
        self.assertEqual(guard.step(2, [4, 5], 0.2), [True, False])
        self.assertEqual(guard.step(3, [0, 2], 0.3), [True, True])
        self.assertEqual(guard.reasons, ['cancelled', 'eos'])
        self.assertEqual(guard.lengths, [2, 3])
        self.assertEqual(guard.finished_at, [0.2, 0.3])

    def test_timeout_and_repetition_only_stop_their_row(self):
        guard = RowStops(3, [2], 512, deadlines={0: 0.01})
        repeated = [1] * 192
        distinct = list(range(192))
        self.assertEqual(guard.step(192, [4, 4, 4], 0.1, [distinct, repeated, distinct]), [True, True, False])
        self.assertEqual(guard.reasons, ['time_limit', 'repetition_stop', None])
        self.assertEqual(guard.step(193, [0, 0, 2], 0.2), [True, True, True])
        self.assertEqual(guard.reasons[-1], 'eos')

    def test_length_limit_and_eos_are_distinct(self):
        guard = RowStops(2, [2, 3], 4)
        self.assertEqual(guard.step(4, [2, 9], 0.1), [True, True])
        self.assertEqual(guard.reasons, ['eos', 'token_limit'])


if __name__ == '__main__':
    unittest.main()
