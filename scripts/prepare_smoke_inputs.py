"""Prepare a small local-only input set; never changes source documents."""

import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "output" / "smoke-test" / "inputs"
    output.mkdir(parents=True, exist_ok=True)
    samples = []
    with pdfium.PdfDocument(args.report) as doc:
        for page_number in [4, 12]:
            page = doc[page_number - 1]
            bitmap = page.render(scale=2)
            image = bitmap.to_pil().convert("RGB")
            name = f"medical-page-{page_number:02}"
            image.save(output / f"{name}.png")
            samples.append({"id": name, "image": str(output / f"{name}.png"), "source": str(args.report), "page": page_number, "task": "table" if page_number == 12 else "ocr"})
            page.close()
    with Image.open(args.certificate) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        image.thumbnail((1800, 1800))
        image.save(output / "certificate.png")
    samples.append({"id": "certificate", "image": str(output / "certificate.png"), "source": str(args.certificate), "page": 1, "task": "ocr"})
    (output / "manifest.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Prepared {len(samples)} samples at {output}")


if __name__ == "__main__":
    main()
