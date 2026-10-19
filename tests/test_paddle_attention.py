"""Exact installed vision attention, random CPU tensors; no weights or CUDA."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional, Tuple
import unittest
from unittest.mock import patch

try:
    import torch
    from torch import nn
    from transformers.integrations.sdpa_attention import sdpa_attention_forward
except ImportError:
    torch = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(torch is None, 'Run explicitly in the Paddle environment; app has no Torch dependency')
class PaddleIsolationTests(unittest.TestCase):
    def setUp(self):
        from ocr_app.paddle_attention import install_paddle_vision_isolation
        tree = ast.parse((ROOT / 'models/paddleocr-vl/modeling_paddleocr_vl.py').read_text(encoding='utf-8'))
        wanted = {'PaddleOCRAttention', 'eager_attention_forward', 'rotate_half', 'apply_rotary_pos_emb_vision'}
        nodes = {node.name: node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in wanted}
        scope = dict(torch=torch, nn=nn, Callable=Callable, List=List, Optional=Optional, Tuple=Tuple,
                     PaddleOCRVisionConfig=SimpleNamespace, sdpa_attention_forward=sdpa_attention_forward)
        exec(compile(ast.Module(body=list(nodes.values()), type_ignores=[]), '<installed-paddle-vision>', 'exec'), scope)
        self.module = SimpleNamespace(PaddleOCRAttention=scope['PaddleOCRAttention'])
        self.original = self.module.PaddleOCRAttention.forward
        self.install = install_paddle_vision_isolation
        self.install(self.module)
        torch.manual_seed(19)
        self.attention = self.module.PaddleOCRAttention(SimpleNamespace(hidden_size=8, num_attention_heads=2,
            attention_dropout=0., _attn_implementation='sdpa')).eval()

    def test_peer_replacement_does_not_change_first_image(self):
        image = torch.randn(1, 2, 8)
        peer = torch.randn(1, 3, 8)
        boundaries = torch.tensor([0, 2, 5])
        expected = self.original(self.attention, image, cu_seqlens=torch.tensor([0, 2]))[0]
        actual = self.attention(torch.cat([image, peer], dim=1), cu_seqlens=boundaries)[0]
        changed = self.attention(torch.cat([image, peer * 10], dim=1), cu_seqlens=boundaries)[0]
        torch.testing.assert_close(actual[:, :2], expected)
        torch.testing.assert_close(changed[:, :2], expected)

    def test_rope_and_existing_mask_follow_unequal_segments(self):
        image = torch.randn(1, 7, 8)
        rope = (torch.randn(7, 4), torch.randn(7, 4))
        mask = torch.zeros(1, 1, 7, 7)
        mask[..., 0, 1] = float('-inf')
        actual = self.attention(image, attention_mask=mask, cu_seqlens=torch.tensor([0, 2, 3, 7]), rope_emb=rope)[0]
        expected = []
        for start, end in [(0, 2), (2, 3), (3, 7)]:
            value = self.original(self.attention, image[:, start:end], attention_mask=mask[..., start:end, start:end],
                cu_seqlens=torch.tensor([0, end-start]), rope_emb=tuple(v[start:end] for v in rope))[0]
            expected.append(value)
        torch.testing.assert_close(actual, torch.cat(expected, dim=1))

    def test_single_image_and_repeated_installation_preserve_original_path(self):
        forward = self.module.PaddleOCRAttention.forward
        self.assertEqual(self.install(self.module), 'segmented_sdpa_v1')
        self.assertIs(self.module.PaddleOCRAttention.forward, forward)
        image = torch.randn(1, 3, 8)
        original = self.original(self.attention, image, cu_seqlens=torch.tensor([0, 3]))[0]
        with patch.object(torch.Tensor, 'tolist', side_effect=AssertionError('Unneeded device-to-host transfer')):
            torch.testing.assert_close(self.attention(image, cu_seqlens=torch.tensor([0, 3]))[0], original, rtol=0, atol=0)
        self.attention.config._attn_implementation = 'eager'
        torch.testing.assert_close(self.attention(image, cu_seqlens=torch.tensor([0, 1, 3]))[0],
            self.original(self.attention, image, cu_seqlens=torch.tensor([0, 1, 3]))[0], rtol=0, atol=0)

    def test_bad_segments_and_debug_attention_fail_before_unisolated_execution(self):
        image = torch.randn(1, 5, 8)
        for boundaries in [[1, 3, 5], [0, 2, 4], [0, 3, 2, 5], [0, 2, 2, 5], [0., 2.5, 5.]]:
            with self.subTest(boundaries=boundaries), self.assertRaises(ValueError):
                self.attention(image, cu_seqlens=torch.tensor(boundaries))
        with self.assertRaises(ValueError):
            self.attention(image, cu_seqlens=torch.tensor([0, 2, 5]), output_attentions=True)
        with self.assertRaises(ValueError):
            self.attention(image, cu_seqlens=torch.tensor([0, 2, 5]), rope_emb=(torch.ones(4, 4), torch.zeros(4, 4)))


if __name__ == '__main__':
    unittest.main()
