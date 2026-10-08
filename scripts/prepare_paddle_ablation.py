"""Freeze seven baseline pages and their predefined semantic regions."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/paddle-ablation-20260929'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    target = OUT / 'inputs/manifest.json'
    if target.exists():
        raise FileExistsError(f'Frozen manifest already exists: {target}')
    refs = read(OUT / 'references.json')['samples']
    sources = {}
    for batch in ['benchmark-rerun-20260929', 'medical-expansion-20260929']:
        for sample in read(ROOT / 'output' / batch / 'inputs/manifest.json'):
            sources[sample['id']] = {**sample, 'baseline_batch': batch}
    crops = read(OUT / 'inputs/crops-manifest.json')
    assert isinstance(crops, list)
    order = ['medical-01-blood-p13', 'cert-020-p1', 'cert-023-p1', 'cert-026-p1',
             'medical-01-followup-long-jpg', 'medical-02-blood-p13', 'medical-03-blood-p12']
    assert set(order) == set(refs)
    manifest = []
    for sid in order:
        base = sources[sid]
        manifest.append({**base, 'id': 'baseline--' + sid, 'parent_id': sid, 'variant': 'baseline'})
        regions = [s for s in crops if s['parent_id'] == sid]
        assert regions, sid
        manifest.extend({**s, 'variant': 'split'} for s in regions)
    assert len(manifest) == 17 and len({s['id'] for s in manifest}) == 17
    for sample in manifest:
        digest = hashlib.sha256(Path(sample['image']).read_bytes()).hexdigest()
        assert not sample.get('input_sha256') or sample['input_sha256'] == digest
        sample['input_sha256'] = digest
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    protocol = {
        'created_at': datetime.now().astimezone().isoformat(),
        'model': 'paddleocr-vl', 'max_new_tokens_per_region': 4096, 'do_sample': False,
        'precision': 'BF16', 'model_revision': read(ROOT/'models/paddleocr-vl/download_manifest.json')['revision'],
        'variants': ['baseline', 'split'], 'parent_pages': 7, 'measured_requests': 17,
        'warmups': 1, 'repeats': 1, 'gpu_concurrency': 1,
        'order': 'one baseline control warmup; then baseline and split interleaved by parent page',
        'scope': 'combined input intervention: remove irrelevant margins, rotation where needed, semantic crops before resizing; not an isolated crop-only causal test',
        'layout_selection': 'assistant predefined visual boundaries; not an automatic official layout pipeline',
        'accuracy': 'same fixed 118 reference fields; actual OCR field assignment reviewed after generation',
        'timing': 'sum seconds for every region, including failed regions; request_wall_seconds includes image IO/decode/output writing; region preparation and merge reported separately',
        'token_budget': '4096 per region, so split pages may use more total tokens than a single baseline page',
        'failure': 'any region error, token limit, or degenerate repetition makes the parent incomplete; termination alone is not success',
    }
    (OUT/'protocol.json').write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'parents': 7, 'requests': len(manifest), 'manifest': str(target)}))


if __name__ == '__main__':
    main()
