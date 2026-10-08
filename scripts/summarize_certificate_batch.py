"""Build local review artifacts; string coverage is not field accuracy."""

import csv
import html
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "output/certificate-batch"
MODELS = ["glm-ocr", "paddleocr-vl", "chandra"]


def compact(text):
    return re.sub(r"\s+", "", html.unescape(re.sub(r"<[^>]*>", "", text)))


def main():
    samples = json.loads((ROOT / "inputs/manifest.json").read_text(encoding="utf-8"))
    references = json.loads((ROOT / "review-reference.json").read_text(encoding="utf-8"))
    refs = {r["id"]: r for r in references["samples"]}
    metrics, fields, cards = [], [], []
    for sample in samples:
        sid = sample["id"]
        ref = refs.get(sid, {})
        details = []
        for model in MODELS:
            path = ROOT / model / f"{sid}.metrics.json"
            if not path.exists():
                details.append(f"<p>{model}：未运行</p>")
                continue
            metric = json.loads(path.read_text(encoding="utf-8"))
            metrics.append(metric)
            raw_path = ROOT / model / f"{sid}.txt"
            raw = raw_path.read_text(encoding="utf-8") if raw_path.exists() else metric.get("error", "无文本")
            differences = []
            for field, expected in ref.get("checks", {}).items():
                present = compact(expected) in compact(raw)
                fields.append({"sample_id": sid, "model": model, "field": field, "reference": expected, "reference_found_in_output": present})
                if not present:
                    differences.append(f"{field}：{expected}")
            status = metric["status"] + (" / 截断" if metric.get("hit_token_limit") else "")
            links = f'<a href="{model}/{sid}.txt">原文</a> · <a href="{model}/{sid}.metrics.json">指标</a>'
            note = "未找到核对字符串：" + "；".join(differences) if differences else "有核对值的项目未发现字符串缺失（不等于字段归属正确）" if ref else "此样本尚未逐字段标注"
            details.append(f'<details><summary>{model} · {html.escape(status)} · {metric.get("seconds", "-")} 秒</summary><p>{links}</p><p>{html.escape(note)}</p><pre>{html.escape(raw)}</pre></details>')
        label = f'{sid} · {Path(sample["source"]).name}'
        notes = f'{ref.get("type", "待逐项核对")}；{"、".join(ref.get("tags", []))}。{ref.get("note", "")}'
        if ref.get("uncertain_fields"):
            notes += " 不确定、不计分：" + "、".join(ref["uncertain_fields"])
        cards.append(f'<article id="{sid}"><h2>{html.escape(label)}</h2><p>{html.escape(notes)}</p><div class="row"><a href="inputs/{sid}.png" target="_blank"><img loading="lazy" src="inputs/{sid}.png" alt="{sid}"></a><section>{"".join(details)}</section></div></article>')
    stats = []
    for model in MODELS:
        runs = [r for r in metrics if r["model"] == model]
        finished = [r for r in runs if r["status"] == "ok" and not r.get("hit_token_limit")]
        times = [r["seconds"] for r in finished]
        stats.append({"model": model, "attempted": len(runs), "completed_without_truncation": len(finished), "errors_or_truncation": len(runs)-len(finished), "generation_seconds_total": round(sum(r.get("seconds", 0) for r in runs), 2), "median_completed_seconds": round(statistics.median(times), 2) if times else None, "max_allocated_gib": max([r.get("peak_allocated_gib", 0) for r in runs], default=0)})
    (ROOT / "summary.json").write_text(json.dumps({"stats": stats, "reference_checks": fields}, ensure_ascii=False, indent=2), encoding="utf-8")
    if fields:
        with (ROOT / "reference-checks.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(fields[0]))
            writer.writeheader()
            writer.writerows(fields)
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>证书 OCR 对照</title><style>body{font:16px system-ui;max-width:1500px;margin:auto;padding:24px;background:#f5f6f8;color:#172033}article{background:white;border-radius:12px;padding:20px;margin:24px 0}h2{font-size:20px}.row{display:grid;grid-template-columns:45% 1fr;gap:24px}img{width:100%;max-height:700px;object-fit:contain}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f7;padding:14px;font-size:14px}details{border:1px solid #ccd3dd;padding:14px;margin-bottom:12px}summary{cursor:pointer;font-weight:600}a{color:#1754b3}@media(max-width:850px){.row{grid-template-columns:1fr}}</style><h1>证书 OCR 对照</h1><p>34 份材料；GLM/Paddle 全量，Chandra 选样。点击图片可查看大图，展开模型名称查看原始结果。数据和图片均为本地文件。</p><p>核对值由助手对照原图初步记录，未经人工双审。字符串出现不代表字段归属正确，也不用于判断证件真实性。错误、截断和未运行分别显示；未标注字段不计准确率。</p>' + ''.join(cards) + '</html>'
    (ROOT / "comparison.html").write_text(document, encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(json.dumps([x for x in fields if not x["reference_found_in_output"]], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
