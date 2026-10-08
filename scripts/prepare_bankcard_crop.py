"""A manually selected diagnostic crop, not an automatic card detector."""

import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
base = ROOT / "output/bankcard-baseline"
output = ROOT / "output/bankcard-crop/inputs"
output.mkdir(parents=True, exist_ok=True)
samples = json.loads((base / "inputs/manifest.json").read_text(encoding="utf-8"))
sample = next(s for s in samples if s["id"] == "bank-002-p1")
with Image.open(sample["image"]) as image:
    upright = image.rotate(-90, expand=True)
    cropped = upright.crop((160, 188, 565, 425)).resize((1215, 711), Image.Resampling.LANCZOS)
    target = output / "bank-002-p1.png"
    cropped.save(target)
    record = {**sample, "image": str(target), "input_size": list(cropped.size),
              "preprocessing": {"rotation_clockwise_degrees": 90, "manual_card_box_after_rotation": [160, 188, 565, 425],
                                "scale_factor": 3, "interpolation": "LANCZOS", "selection": "manual_after_GLM_baseline_failure"}}
(output / "manifest.json").write_text(json.dumps([record], ensure_ascii=False, indent=2), encoding="utf-8")
print("Prepared one manually selected crop of bank-002-p1")
