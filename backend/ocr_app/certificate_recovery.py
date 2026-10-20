"""One observed context crop; recovery never overwrites a primary field."""
import math
import re

from .doc_profiles import profile
from .extraction import DIPLOMA, DEGREE, extract_fields


RECOVERY_TYPES = frozenset({'DIPLOMA', 'DEGREE_CERT'})


def missing_required_fields(evidence, doc_type, overrides=None):
    fields = {f['key']: f for f in extract_fields(evidence, doc_type)}
    values = {key: field.get('value') for key, field in fields.items()}
    return [meta['key'] for meta in profile(doc_type, values, overrides)
            if meta['required'] and meta['editable'] and
            not fields[meta['key']].get('candidates') and
            (values[meta['key']] is None or isinstance(values[meta['key']], str) and not values[meta['key']].strip())]


def locate_recovery_region(image, doc_type, keys, check):
    from .table_recognition import nearby_text
    dictionary = DIPLOMA if doc_type == 'DIPLOMA' else DEGREE
    labels = {key: dictionary[key][1] for key in keys if key in dictionary}
    probe = image.copy()
    probe.thumbnail((1600, 1600))
    check()
    observed = nearby_text(probe, [], check)
    check()
    lines = []
    for line in observed:
        box = line.get('box', [])
        if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            continue
        if not (0 <= box[0] < box[2] <= probe.width and 0 <= box[1] < box[3] <= probe.height):
            continue
        text = re.sub(r'\s+', '', line['text'])
        hits = {key for key, aliases in labels.items() if any(re.sub(r'\s+', '', a) in text for a in aliases)}
        lines.append(dict(box=box, keys=hits))
    candidates = []
    for anchor in (line for line in lines if line['keys']):
        height = anchor['box'][3] - anchor['box'][1]
        top, bottom = anchor['box'][1] - height * 2, anchor['box'][3] + height * 2
        neighbors = [line for line in lines if top <= (line['box'][1] + line['box'][3]) / 2 <= bottom]
        margin = max(4, height * .2)
        box = [max(0, min(l['box'][0] for l in neighbors) - margin),
               max(0, min(l['box'][1] for l in neighbors) - margin),
               min(probe.width, max(l['box'][2] for l in neighbors) + margin),
               min(probe.height, max(l['box'][3] for l in neighbors) + margin)]
        # Extremely thin strips lose document context and can provoke repetition.
        required_height = math.ceil((box[2] - box[0]) / 2.3)
        if required_height > box[3] - box[1]:
            center = (box[1] + box[3]) / 2
            box[1] = max(0, min(center - required_height / 2, probe.height - required_height))
            box[3] = min(probe.height, box[1] + required_height)
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area >= probe.width * probe.height * .65:
            continue
        supported = set().union(*(line['keys'] for line in neighbors))
        scaled = tuple(round(v * (image.width / probe.width if i % 2 == 0 else image.height / probe.height))
                       for i, v in enumerate(box))
        candidates.append((len(supported), -area, dict(box=scaled, keys=[key for key in keys if key in supported])))
    return max(candidates, key=lambda item: item[:2])[2] if candidates else None


def merge_recovery_fields(result, evidence, recoveries, recognized_ids):
    """Keep all raw text, but only successful recovery may supply missing targets."""
    primary = [block for block in evidence if block['region_id'] not in recoveries]
    supplemental = [block for block in evidence if block['region_id'] in recognized_ids]
    original = {f['key']: f for f in extract_fields(primary, result['doc_type'])}
    recovered = {f['key']: f for f in extract_fields(supplemental, result['doc_type'])}
    targets = set().union(*(set(recoveries[region_id]) for region_id in recognized_ids)) if recognized_ids else set()
    for index, current in enumerate(result['fields']):
        key = current['key']
        field = original[key]
        if key in targets and field.get('value') is None and not field.get('candidates'):
            candidate = recovered[key]
            if candidate.get('value') is not None or candidate.get('candidates'):
                field = candidate
        field.update(required=current['required'], editable=current['editable'])
        result['fields'][index] = field
