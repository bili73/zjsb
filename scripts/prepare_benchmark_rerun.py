"""Freeze the same 16 image inputs for all three models without changing old runs."""
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/benchmark-rerun-20260929"
refs = json.loads((ROOT / "output/certificate-batch/review-reference.json").read_text(encoding="utf-8"))
certificate_ids = {r["id"] for r in refs["samples"]}
manifest = []
for batch, group in [("certificate-batch", "certificate"), ("smoke-test", "medical_report"),
                     ("bankcard-baseline", "bankcard_original"), ("bankcard-crop", "bankcard_crop")]:
    samples = json.loads((ROOT / "output" / batch / "inputs/manifest.json").read_text(encoding="utf-8"))
    for sample in samples:
        if batch == "certificate-batch" and sample["id"] not in certificate_ids:
            continue
        if batch == "smoke-test" and not sample["id"].startswith("medical-"):
            continue
        sid = "crop-" + sample["id"] if batch == "bankcard-crop" else sample["id"]
        manifest.append({**sample, "id": sid, "original_sample_id": sample["id"], "original_batch": batch,
                         "group": group, "input_sha256": hashlib.sha256(Path(sample["image"]).read_bytes()).hexdigest()})
assert len(manifest) == 16 and len({r["id"] for r in manifest}) == 16
if OUT.exists():
    raise RuntimeError("Rerun directory already exists; refusing to overwrite measurements")
(OUT / "inputs").mkdir(parents=True)
(OUT / "inputs/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "protocol.json").write_text(json.dumps({
    "created_at": datetime.now().astimezone().isoformat(), "models": ["glm-ocr", "paddleocr-vl", "chandra"],
    "input_count_per_model": 16, "warmup_count_per_model": 1, "measured_repeats": 1, "max_new_tokens": 4096,
    "timing": "processor+transfer+generation; loading, image IO, decoding, file writing and GPU snapshots excluded",
    "comparison": "group-specific intersection of inputs completed without truncation by all three models",
    "failures": "retain truncation/error timing separately; completion rate uses every measured input",
    "gpu_observation": "snapshots before and after every input, not continuous monitoring",
    "precision": {"glm-ocr": "BF16", "paddleocr-vl": "BF16", "chandra": "NF4 with BF16 compute"}
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Prepared {len(manifest)} identical inputs per model at {OUT}")
