"""Export the separate four-region follow-up; does not alter the first experiment."""
import csv
import json
from datetime import datetime
from pathlib import Path

from export_paddle_ablation import ROOT, sha, read, normalize, total, field_score, relative

RUN = ROOT / "output/paddle-ablation-20260929/refinement"
PARENT = "cert-026-p1"


def main():
    manifest_path = RUN / "inputs/manifest.json"
    samples = read(manifest_path)
    assert len(samples) == 4 and len({s["id"] for s in samples}) == 4
    assert all(s["parent_id"] == PARENT for s in samples)
    ref_path = RUN.parent / "references.json"
    refs = read(ref_path)
    ref = refs["samples"][PARENT]
    assert len(ref["fields"]) == 5
    review_path = RUN / "reviewed-predictions.json"
    reviews = read(review_path) if review_path.exists() else {}
    assert not reviews or reviews["parent_id"] == PARENT
    predictions = reviews.get("fields", {})
    region_reviews = reviews.get("region_reviews", {})
    prep_path = RUN / "inputs/crop-preparation.json"
    if prep_path.exists():
        parents = read(prep_path)["parents"]
        preparation = next(p["preparation_seconds"] for p in parents if p["parent_id"] == PARENT)
    else:
        timings = {s.get("preparation_seconds") for s in samples}
        assert len(timings) == 1, "Per-parent preparation time must match across region rows"
        preparation = timings.pop()
    metric_paths = {p.name.removesuffix(".metrics.json"): p for p in (RUN / "paddleocr-vl").glob("*.metrics.json")}
    definitions = [(s, s["id"], "measurement") for s in samples]
    for request_id in metric_paths:
        if request_id.startswith("warmup-"):
            sample = next(s for s in samples if s["id"] == request_id.removeprefix("warmup-"))
            definitions.append((sample, request_id, "warmup"))
    audit = {"created_at": datetime.now().astimezone().isoformat(), "manifest_sha256": sha(manifest_path),
             "reference_file": relative(ref_path), "reference_sha256": sha(ref_path),
             "review_sha256": sha(review_path) if review_path.exists() else None, "hash_checks": [],
             "scope": "post-hoc targeted follow-up, four fresh requests; initial experiment remains unchanged"}
    for path, expected in refs["source_reference_sha256"].items():
        assert sha(ROOT / path).lower() == expected.lower(), "Source reference changed"
    for sample in samples:
        for file_key, hash_key in [("image", "input_sha256"), ("source", "source_sha256"), ("crop_source", "crop_source_sha256")]:
            if file_key in sample and hash_key in sample:
                assert sha(Path(sample[file_key])).lower() == sample[hash_key].lower(), f"Source changed: {sample['id']}"
        audit["hash_checks"].append({"request_id": sample["id"], "input_sha256": sample["input_sha256"], "matches": True})
    regions = []
    for sample, request_id, phase in definitions:
        path = metric_paths.get(request_id)
        metric = read(path) if path else {}
        raw_path = RUN / "paddleocr-vl" / f"{request_id}.txt"
        valid = bool(metric) and raw_path.exists()
        if valid:
            valid = len(raw_path.read_text(encoding="utf-8")) == metric.get("characters")
        if metric:
            assert metric["model"] == "paddleocr-vl" and metric["sample_id"] == request_id
            assert metric["source"] == sample["source"] and metric["page"] == sample["page"]
            assert metric["model_revision"] == "7fa00a8c55b735ba51ba49a9058f3f9c57a99a11" and metric["max_new_tokens"] == 4096
        review = region_reviews.get(request_id, {})
        reviewed = isinstance(review.get("degenerate_repetition"), bool)
        technical = int(metric.get("status") == "ok" and not metric.get("hit_token_limit") and valid) if metric else None
        complete = 0 if technical == 0 or review.get("degenerate_repetition") is True else 1 if technical == 1 and reviewed else None
        regions.append({"parent_id": PARENT, "request_id": request_id, "phase": phase,
            "region_name": sample.get("region_name"), "region_index": sample.get("region_index"),
            "recorded": int(bool(metric)), "status": metric.get("status", "missing_metric"), "completed": complete,
            "technical_completed": technical, "reviewed": int(reviewed),
            "token_limit": int(bool(metric.get("hit_token_limit"))) if metric else None,
            "degenerate_repetition": int(review["degenerate_repetition"]) if reviewed else None,
            "review_notes": review.get("notes"), "seconds": metric.get("seconds"),
            "failed_wall_seconds": metric.get("failed_wall_seconds"),
            "recognition_or_failed_interval_seconds": metric.get("seconds", metric.get("failed_wall_seconds")),
            "request_wall_seconds": metric.get("request_wall_seconds"), "output_tokens": metric.get("output_tokens"),
            "max_new_tokens": 4096, "peak_allocated_gib": metric.get("peak_allocated_gib"),
            "process_id": metric.get("process_id"), "started_at": metric.get("started_at"), "finished_at": metric.get("finished_at"),
            "input_sha256": sample["input_sha256"], "output_valid": int(valid), "output_sha256": sha(raw_path) if valid else None,
            "metric_file": relative(path) if path else None, "output_file": relative(raw_path) if valid else None})
    measured = [r for r in regions if r["phase"] == "measurement"]
    all_recorded = all(r["recorded"] for r in measured)
    checks = []
    for field, expected in ref["fields"].items():
        reviewed = field in predictions and all_recorded
        value = predictions.get(field)
        checks.append({"parent_id": PARENT, "field": field, "reference_value": expected, "predicted_value": value,
            "reviewed": int(reviewed), "exact_match": int(value is not None and normalize(value, ref["normalization"]) == normalize(expected, ref["normalization"])) if reviewed else None,
            "normalization": ref["normalization"], "reference_status": ref["reference_status"]})
    complete = 0 if any(r["completed"] == 0 for r in measured) else 1 if all(r["completed"] == 1 for r in measured) else None
    wall = total(r["request_wall_seconds"] for r in measured)
    summary = [{"parent_id": PARENT, "variant": "targeted_four_region_followup", "expected_regions": 4,
        "recorded_regions": sum(r["recorded"] for r in measured), "completed": complete,
        "status": "completed" if complete == 1 else "incomplete" if complete == 0 else "review_pending" if all_recorded else "missing_metric",
        "token_limit_regions": sum(r["token_limit"] or 0 for r in measured),
        "degenerate_regions": sum(r["degenerate_repetition"] or 0 for r in measured),
        "recognition_seconds_sum": total(r["recognition_or_failed_interval_seconds"] for r in measured),
        "recorded_recognition_seconds_sum": sum(r["recognition_or_failed_interval_seconds"] for r in measured if r["recognition_or_failed_interval_seconds"] is not None),
        "request_wall_seconds_sum": wall, "preparation_seconds": preparation,
        "request_plus_preparation_seconds": total([wall, preparation]), "end_to_end_seconds": None,
        "output_tokens": total(r["output_tokens"] for r in measured), "max_page_tokens_budget": 4*4096,
        **field_score(checks)}]
    audit.update(process_ids=sorted({r["process_id"] for r in regions if r["recorded"]}),
                 warmups=sum(r["phase"] == "warmup" for r in regions),
                 missing_requests=[r["request_id"] for r in measured if not r["recorded"]])
    assert len(audit["process_ids"]) <= 1
    out = RUN / "data"
    out.mkdir(parents=True, exist_ok=True)
    payload = {"exported_at": audit["created_at"], "regions": regions, "checks": checks, "summary": summary, "audit": audit}
    (out / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("regions", "checks", "summary"):
        rows = payload[name]
        with (out / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (out / "README.md").write_text("""# 定向四区域补测

这是初轮失败后调整边界的单次定向补测，不能替代初轮记录或并入初轮总体准确率。4个fresh区域全部计时；预热排除。准备耗时按父页只加一次。总token预算为4×4096，和初轮2区域不同。转正/裁剪/有效分辨率及人工选框不属于自动官方pipeline。

同一冻结5字段，实际字段所属关系经审核；未核对准确率留空，已核对缺失计错。页面完成要求全部区域未限长、未复读且技术成功。识别计算耗时含全部区域，包括失败；若只有failed_wall_seconds则保留实际失败区间。request_plus_preparation_seconds不包含人工决策和结果合并，不能称生产端到端速度，end_to_end_seconds未知。源文本和哈希保留，未根据参考修正或去重输出。
""", encoding="utf-8")
    print(json.dumps({"recorded_regions": summary[0]["recorded_regions"], "completed": complete,
                      "reviewed_fields": summary[0]["field_reviewed"], "field_accuracy": summary[0]["field_accuracy"]}))


if __name__ == "__main__":
    main()
