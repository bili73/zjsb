"""Offline safe diagnostic export; works without the API or model dependencies."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.diagnostics import DEFAULT_ROOT, collect_diagnostics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serious-stream', action='store_true', help='Read-only serious-event ZIP on stdout; no keys or writable source required')
    args = parser.parse_args()
    if args.serious_stream:
        from ocr_app.diagnostic_offline import source_bundle
        sys.stdout.buffer.write(source_bundle(args.root))
        return 0
    destination = args.output or ROOT / 'output' / ('diagnostics-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.zip')
    try:
        result = collect_diagnostics(args.root, destination)
    except Exception:
        print('DIAGNOSTICS_EXPORT_FAILED: check destination access and use a new output filename.', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True))
    print('Diagnostic bundle: ' + str(destination.resolve()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
