"""Isolate packed images in the original Paddle checkpoint's SDPA vision path."""
from functools import wraps
import inspect

ISOLATION_VERSION = 'segmented_sdpa_v1'


def install_paddle_vision_isolation(module):
    attention = module.PaddleOCRAttention
    original = attention.forward
    if getattr(original, '_ocr_image_isolation', None) == ISOLATION_VERSION:
        return ISOLATION_VERSION
    expected = ['self', 'hidden_states', 'attention_mask', 'output_attentions', 'cu_seqlens', 'rope_emb']
    if list(inspect.signature(original).parameters) != expected:
        raise RuntimeError('UNSUPPORTED_PADDLE_VISION_ATTENTION')

    @wraps(original)
    def isolated(self, hidden_states, attention_mask=None, output_attentions=False, cu_seqlens=None, rope_emb=None):
        if self.config._attn_implementation != 'sdpa' or cu_seqlens is None:
            return original(self, hidden_states, attention_mask, output_attentions, cu_seqlens, rope_emb)
        # Preserve the normal one-image path without a device-to-host sync per layer.
        if cu_seqlens.ndim == 1 and cu_seqlens.numel() == 2:
            return original(self, hidden_states, attention_mask, output_attentions, cu_seqlens, rope_emb)
        boundaries = cu_seqlens.tolist()
        length = hidden_states.shape[1]
        if (not isinstance(boundaries, list) or len(boundaries) < 2
                or any(type(value) is not int for value in boundaries)
                or boundaries[0] != 0 or boundaries[-1] != length
                or any(end <= start for start, end in zip(boundaries, boundaries[1:]))):
            raise ValueError('INVALID_PACKED_IMAGE_BOUNDARIES')
        if hidden_states.shape[0] != 1 or output_attentions:
            raise ValueError('UNSUPPORTED_PACKED_VISION_OUTPUT')
        if rope_emb is not None and (len(rope_emb) != 2 or any(value.shape[0] != length for value in rope_emb)):
            raise ValueError('INVALID_PACKED_IMAGE_ROPE')
        if attention_mask is not None and (attention_mask.ndim < 2 or attention_mask.shape[-1] != length
                                          or attention_mask.shape[-2] not in {1, length}):
            raise ValueError('INVALID_PACKED_IMAGE_MASK')
        import torch
        outputs = []
        for start, end in zip(boundaries, boundaries[1:]):
            mask = attention_mask
            if mask is not None:
                mask = mask[..., :1, start:end] if mask.shape[-2] == 1 else mask[..., start:end, start:end]
            rope = tuple(value[start:end] for value in rope_emb) if rope_emb is not None else None
            value, _ = original(self, hidden_states[:, start:end], mask, False,
                                cu_seqlens.new_tensor([0, end-start]), rope)
            outputs.append(value)
        return torch.cat(outputs, dim=1), None

    isolated._ocr_image_isolation = ISOLATION_VERSION
    attention.forward = isolated
    return ISOLATION_VERSION
