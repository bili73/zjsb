"""Export the independent repeated timing pair without replacing original records."""
import csv
import json
from datetime import datetime

from export_paddle_ablation import ROOT, read, sha, relative, normalize, field_score

RUN = ROOT / "output/paddle-ablation-20260929/timing-recheck"


def main():
    manifest_path = RUN / "inputs/manifest.json"
    samples = read(manifest_path)
    assert len(samples) == 2 and {s["variant"] for s in samples} == {"baseline", "split"}
    reference_path = RUN.parent / "references.json"
    refs = read(reference_path)
    reviews = read(RUN / "reviewed-predictions.json")
    runs, checks, summary = [], [], []
    for path in sorted((RUN / "paddleocr-vl").glob("*.metrics.json")):
        metric = read(path)
        request_id = metric["sample_id"]
        sid = request_id.removeprefix("warmup-")
        sample = next(s for s in samples if s["id"] == sid)
        phase = metric["phase"]
        raw_path = path.with_name(request_id + ".txt")
        assert len(raw_path.read_text(encoding="utf-8")) == metric["characters"]
        from pathlib import Path
        assert sha(Path(sample["image"])) == sample["input_sha256"]
        initial_sample = next(s for s in read(RUN.parent / "inputs/manifest.json") if s["id"] == sid)
        assert sample["input_sha256"] == initial_sample["input_sha256"]
        assert metric["model_revision"] == "7fa00a8c55b735ba51ba49a9058f3f9c57a99a11" and metric["max_new_tokens"] == 4096
        review = reviews.get("region_reviews", {}).get(request_id, {})
        reviewed = isinstance(review.get("degenerate_repetition"), bool)
        technical = metric["status"] == "ok" and not metric["hit_token_limit"]
        completed = 0 if not technical or review.get("degenerate_repetition") is True else 1 if reviewed else None
        row = {"request_id": request_id, "parent_id": sample["parent_id"], "variant": sample["variant"], "phase": phase,
               "seconds": metric["seconds"], "recognition_seconds_sum": metric["seconds"],
               "request_wall_seconds": metric.get("request_wall_seconds"), "completed": completed,
               "technical_completed": int(technical), "degenerate_repetition": int(review["degenerate_repetition"]) if reviewed else None,
               "tokens": metric["output_tokens"], "output_tokens": metric["output_tokens"], "max_new_tokens": 4096,
               "process_id": metric["process_id"], "started_at": metric["started_at"], "finished_at": metric["finished_at"],
               "input_sha256": sample["input_sha256"], "output_sha256": sha(raw_path),
               "metric_file": relative(path), "output_file": relative(raw_path)}
        runs.append(row)
        if phase != "measurement":
            continue
        ref = refs["samples"][sample["parent_id"]]
        prediction = reviews.get("variants", {}).get(sample["variant"], {}).get(sample["parent_id"], {})
        page_checks = []
        for field, expected in ref["fields"].items():
            value = prediction.get(field)
            checked = field in prediction
            check = {"variant": sample["variant"], "parent_id": sample["parent_id"], "field": field,
                     "reference_value": expected, "predicted_value": value, "reviewed": int(checked),
                     "exact_match": int(value is not None and normalize(value, ref["normalization"]) == normalize(expected, ref["normalization"])) if checked else None,
                     "normalization": ref["normalization"], "reference_status": ref["reference_status"]}
            checks.append(check)
            page_checks.append(check)
        summary.append({**row, **field_score(page_checks)})
    out = RUN / "data"
    out.mkdir(parents=True, exist_ok=True)
    audit = {"reference_sha256": sha(reference_path), "manifest_sha256": sha(manifest_path),
             "review_sha256": sha(RUN / "reviewed-predictions.json"),
             "scope": "Independent two-request timing repeat after sleep-contaminated initial measurement; does not overwrite, substitute, or average into the initial run"}
    payload = {"exported_at": datetime.now().astimezone().isoformat(), "runs": runs, "checks": checks, "summary": summary, "audit": audit}
    assert len(summary) == 2 and len(checks) == 56
    (out / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("runs", "checks", "summary"):
        rows = payload[name]
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (out / "README.md").write_text("独立计时复核：同一父页的原整页/原裁剪图、相同权重与参数，另1预热不统计。仅2个正式请求，各28冻结字段。原始睡眠干扰记录保留且不替换；本复核不并入初轮平均值，不能用单次复核推断总体提速。所有参考为助手初审。\n", encoding="utf-8")
    print(json.dumps([{k:r[k] for k in ["variant", "seconds", "field_correct", "field_total", "completed"]} for r in summary]))


if __name__ == "__main__":
    main()
