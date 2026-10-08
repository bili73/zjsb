"""Download the selected public OCR checkpoints without accessing input documents."""

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

from huggingface_hub import HfApi, snapshot_download

MODELS = {
    "pp-doclayout-v3": "PaddlePaddle/PP-DocLayoutV3_safetensors",
    "glm-ocr": "zai-org/GLM-OCR",
    "paddleocr-vl": "PaddlePaddle/PaddleOCR-VL",
    "paddleocr-vl-1.6": "PaddlePaddle/PaddleOCR-VL-1.6",
    "chandra": "datalab-to/chandra-ocr-2",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=MODELS)
    args = parser.parse_args()
    repo_id = MODELS[args.model]
    info = HfApi().model_info(repo_id, token=False)
    destination = ROOT / "models" / args.model
    print(f"Downloading {repo_id} @ {info.sha} to {destination}", flush=True)
    snapshot_download(
        repo_id,
        revision=info.sha,
        local_dir=destination,
        token=False,
        max_workers=3,
        allow_patterns=["*.json", "*.safetensors", "*.py", "*.txt", "*.model", "*.jinja", "*.md", "LICENSE*", "*.tiktoken"],
    )
    (destination / "download_manifest.json").write_text(
        json.dumps({"repo_id": repo_id, "revision": info.sha}, indent=2), encoding="utf-8"
    )
    print(f"Download complete: {args.model}", flush=True)


if __name__ == "__main__":
    main()
