"""Prepare local certificate images and visual contact sheets for batch evaluation."""

import argparse
import hashlib
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "output/certificate-batch/inputs")
    parser.add_argument("--prefix", default="cert")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest, inventory = [], []
    hashes = {}
    for index, path in enumerate(sorted(args.source.iterdir()), 1):
        if not path.is_file():
            continue
        record = {"source": str(path), "status": "ok"}
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            record["sha256"] = digest
            record["duplicate_of"] = hashes.get(digest)
            hashes.setdefault(digest, str(path))
            if path.suffix.lower() == ".pdf":
                images = []
                with pdfium.PdfDocument(path) as doc:
                    for page in doc:
                        bitmap = page.render(scale=2)
                        images.append(bitmap.to_pil().convert("RGB"))
                        bitmap.close()
                        page.close()
            else:
                with Image.open(path) as original:
                    record["original_size"] = list(original.size)
                    record["exif_orientation"] = original.getexif().get(274)
                    images = [ImageOps.exif_transpose(original).convert("RGB")]
            record["pages"] = len(images)
            for page_number, image in enumerate(images, 1):
                sample_id = f"{args.prefix}-{index:03d}-p{page_number}"
                image.thumbnail((1600, 1600))
                target = output / f"{sample_id}.png"
                image.save(target)
                manifest.append({"id": sample_id, "image": str(target), "source": str(path), "page": page_number, "task": "ocr", "source_sha256": digest, "input_size": list(image.size)})
        except Exception as error:
            record.update(status="error", error=str(error))
        inventory.append(record)
    for name, data in [("manifest.json", manifest), ("inventory.json", inventory)]:
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for start in range(0, len(manifest), 8):
        sheet = Image.new("RGB", (1600, 900), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        for offset, sample in enumerate(manifest[start:start + 8]):
            x, y = offset % 4 * 400, offset // 4 * 450
            with Image.open(sample["image"]) as image:
                image.thumbnail((386, 414))
                sheet.paste(image, (x + (400-image.width)//2, y + 28 + (414-image.height)//2))
            draw.text((x+10, y+8), sample["id"], fill="black")
        sheet.save(output / f"contact-{start//8+1:02d}.jpg", quality=90)
    failures = [r for r in inventory if r["status"] != "ok"]
    print(json.dumps({"files": len(inventory), "pages": len(manifest), "failures": failures, "duplicates": [r["source"] for r in inventory if r.get("duplicate_of")]}, ensure_ascii=False))
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
