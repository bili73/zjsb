"""Private two-row CUDA generation; application processes never import Torch."""
import base64
import io
import math
import time


def compatible(left, right):
    return (left.get('task', 'ocr'), left.get('max_new_tokens', 4096)) == (
        right.get('task', 'ocr'), right.get('max_new_tokens', 4096))


class RowStops:
    def __init__(self, count, eos, limit, *, deadlines=None):
        self.eos, self.limit, self.deadlines = set(eos), limit, deadlines or {}
        self.reasons, self.lengths = [None] * count, [None] * count

    def step(self, length, last_tokens, elapsed, tails=None, cancelled=()):
        newly_done = []
        for row, token in enumerate(last_tokens):
            if self.reasons[row] is not None:
                continue
            reason = None
            if row in cancelled:
                reason = 'cancelled'
            elif elapsed >= self.deadlines.get(row, math.inf):
                reason = 'time_limit'
            elif token in self.eos:
                reason = 'eos'
            elif tails and len(tails[row]) == 192 and tails[row][:48] == tails[row][48:96] == tails[row][96:144] == tails[row][144:]:
                reason = 'repetition_stop'
            elif length >= self.limit:
                reason = 'token_limit'
            if reason:
                self.reasons[row], self.lengths[row] = reason, length
                newly_done.append(row)
        return [value is not None for value in self.reasons], newly_done


def decode_image(payload):
    from PIL import Image, ImageOps
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
    return image


def generate_rows(engine, rows, controls, on_row):
    """A completed row is emitted once, before an unfinished peer returns."""
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
        raise ValueError('INVALID_BATCH_SIZE')
    ids = [row.get('row_id') for row in rows]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('INVALID_BATCH_IDENTITIES')
    if any(not compatible(rows[0], row) for row in rows):
        raise ValueError('INCOMPATIBLE_BATCH')
    selected, images = [], []
    for row in rows:
        if controls[row['row_id']].is_set():
            on_row(row['row_id'], None, 'CANCELLED')
            continue
        if row['deadline'] <= time.monotonic():
            on_row(row['row_id'], None, 'EXTRACT_TIMEOUT')
            continue
        try:
            images.append(decode_image(row))
        except (OSError, ValueError, TypeError):
            on_row(row['row_id'], None, 'INPUT_INVALID')
            continue
        selected.append(row)
    if not selected:
        return dict(completed=len(rows))
    task, tokens = selected[0].get('task', 'ocr'), selected[0].get('max_new_tokens', 4096)
    if task not in {'ocr', 'table'} or type(tokens) is not int or not 1 <= tokens <= 4096:
        raise ValueError('INVALID_REQUEST')
    from transformers import StoppingCriteria, StoppingCriteriaList
    torch = engine.torch
    tokenizer = engine.processor.tokenizer
    tokenizer.padding_side = 'left'
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    prompt = 'Table Recognition:' if task == 'table' else ('Text Recognition:' if engine.name == 'glm-ocr' else 'OCR:')
    conversations = [[{'role': 'user', 'content': [{'type': 'image', 'image': image}, {'type': 'text', 'text': prompt}]}] for image in images]
    torch.cuda.synchronize()
    began = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    inputs = engine.processor.apply_chat_template(conversations, tokenize=True, add_generation_prompt=True,
        padding=True, return_dict=True, return_tensors='pt').to('cuda')
    if inputs['input_ids'].shape[0] != len(selected):
        raise ValueError('PROCESSOR_BATCH_MISMATCH')
    prompt_length = inputs['input_ids'].shape[1]
    eos = engine.model.generation_config.eos_token_id or tokenizer.eos_token_id
    deadlines = {}
    for index, row in enumerate(selected):
        soft = row.get('generation_timeout_seconds')
        if soft is not None and (type(soft) not in (int, float) or not math.isfinite(soft) or soft <= 0):
            raise ValueError('INVALID_GENERATION_BUDGET')
        deadlines[index] = min(row['deadline'] - began - 10., soft if soft is not None else math.inf)
    stops = RowStops(len(selected), eos if isinstance(eos, list) else [eos], tokens, deadlines=deadlines)
    emitted = set()

    def deliver(index, ids):
        if index in emitted:
            return
        emitted.add(index)
        row = selected[index]
        reason = stops.reasons[index]
        if reason == 'cancelled':
            on_row(row['row_id'], None, 'CANCELLED')
            return
        length = stops.lengths[index]
        on_row(row['row_id'], dict(text=engine.processor.decode(ids[index, prompt_length:prompt_length+length], skip_special_tokens=True),
            output_tokens=length, termination_reason=reason, recognition_seconds=time.monotonic()-began,
            gpu_peak_allocated_gib=torch.cuda.max_memory_allocated()/2**30,
            gpu_peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
            max_new_tokens=tokens, generation_timeout_seconds=row.get('generation_timeout_seconds'),
            batch_size=len(selected)), None)

    class Guard(StoppingCriteria):
        def __call__(self, ids, scores, **kwargs):
            length = ids.shape[1] - prompt_length
            tails = ids[:, -192:].tolist() if length >= 192 and length % 32 == 0 else None
            cancelled = [index for index, row in enumerate(selected) if controls[row['row_id']].is_set()]
            mask, newly_done = stops.step(length, ids[:, -1].tolist(), time.monotonic()-began, tails, cancelled)
            for index in newly_done:
                deliver(index, ids)
            return torch.tensor(mask, dtype=torch.bool, device=ids.device)

    try:
        with torch.inference_mode():
            output = engine.model.generate(**inputs, max_new_tokens=tokens, do_sample=False, use_cache=True,
                pad_token_id=tokenizer.pad_token_id, stopping_criteria=StoppingCriteriaList([Guard()]))
        torch.cuda.synchronize()
        if output.shape[0] != len(selected) or len(emitted) != len(selected):
            raise ValueError('INCOMPLETE_BATCH_OUTPUT')
        return dict(completed=len(rows))
    finally:
        # The next RPC can reuse the weights; no hidden retry or process switch.
        del inputs
        torch.cuda.empty_cache()
