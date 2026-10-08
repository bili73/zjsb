"""Export a fixed paired Paddle input-intervention experiment; CPU/file IO only."""
import csv
import hashlib
import json
import re
import statistics
import time
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "output/paddle-ablation-20260929"
OUT = RUN / "data"
FAILURE_IDS = {"cert-020-p1", "cert-023-p1", "cert-026-p1", "medical-01-followup-long-jpg"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path):
    return path.relative_to(ROOT).as_posix()


def normalize(value, rule):
    value = str(value)
    if "NFKC" in rule:
        value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", "", value)


def total(values):
    values = list(values)
    return sum(values) if values and all(v is not None for v in values) else None


def average(values):
    values = list(values)
    return statistics.mean(values) if values and all(v is not None for v in values) else None


def field_score(checks, prefix="field"):
    reviewed = [c for c in checks if c["reviewed"]]
    all_reviewed = bool(checks) and len(reviewed) == len(checks)
    return {prefix+"_correct": sum(c["exact_match"] for c in reviewed) if reviewed else None,
            prefix+"_total": len(checks), prefix+"_reviewed": len(reviewed),
            prefix+"_accuracy": sum(c["exact_match"] for c in reviewed)/len(checks) if all_reviewed else None}


def merge_page(variant, parent, rows):
    if not all(r["output_valid"] for r in rows):
        return None
    inputs = [{"request_id": r["request_id"], "output_sha256": r["output_sha256"]} for r in rows]
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    folder = RUN / "merged" / variant
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{parent}--{digest[:16]}.txt"
    metric_path = folder / f"{parent}--{digest[:16]}.merge.metrics.json"
    if metric_path.exists():
        saved = read(metric_path)
        assert saved["inputs"] == inputs and saved["output_sha256"] == sha(path), "Merged artifact changed"
        return saved
    # Read all region texts, concatenate in frozen manifest order, and save without filtering.
    started = time.perf_counter()
    texts = [(ROOT / r["output_file"]).read_text(encoding="utf-8") for r in rows]
    merged = "\n\n".join(texts)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(merged)
        stream.flush()
    elapsed = time.perf_counter()-started
    saved = {"created_at": datetime.now().astimezone().isoformat(), "inputs": inputs,
             "input_fingerprint": digest, "output_sha256": sha(path), "output_file": relative(path),
             "merge_seconds": elapsed, "characters": len(merged),
             "scope": "read region text files + concatenate with two newline separators + write and flush merged file; no fsync; excludes hashing and metadata write"}
    metric_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


def main():
    manifest_path = RUN / "inputs/manifest.json"
    refs_path = RUN / "references.json"
    samples = read(manifest_path)
    refs = read(refs_path)
    protocol = read(RUN / "protocol.json")
    review_path = RUN / "reviewed-predictions.json"
    reviews = read(review_path) if review_path.exists() else {}
    predictions = reviews.get("variants", {})
    region_reviews = reviews.get("region_reviews", {})
    exclusion_path = RUN / "timing-exclusions.json"
    timing_exclusions = read(exclusion_path).get("requests", {}) if exclusion_path.exists() else {}
    preparations = {p["parent_id"]: p for p in read(RUN / "inputs/crop-preparation.json")["parents"]}
    assert len(samples) == 17 and len({s["id"] for s in samples}) == 17
    assert sum(len(s["fields"]) for s in refs["samples"].values()) == 118
    audit = {"created_at": datetime.now().astimezone().isoformat(), "manifest_sha256": sha(manifest_path),
             "references_sha256": sha(refs_path), "review_sha256": sha(review_path) if review_path.exists() else None,
             "source_reference_checks": [], "input_checks": [], "corrupt_metrics": [],
             "unexpected_metrics": [], "protocol": protocol}
    for path, expected in refs["source_reference_sha256"].items():
        actual = sha(ROOT / path)
        assert actual.lower() == expected.lower(), f"Frozen source reference changed: {path}"
        audit["source_reference_checks"].append({"file": path, "sha256": actual, "matches": True})
    checked = {}
    for sample in samples:
        for path_key, hash_key in [("image", "input_sha256"), ("source", "source_sha256"), ("crop_source", "crop_source_sha256")]:
            if path_key not in sample:
                continue
            path = Path(sample[path_key])
            actual = checked.setdefault(str(path), sha(path))
            assert actual == sample[hash_key], f"Input/source changed: {sample['id']}/{path_key}"
        audit["input_checks"].append({"request_id": sample["id"], "input_sha256": sample["input_sha256"], "matches": True})
    metrics = {}
    for path in (RUN / "paddleocr-vl").glob("*.metrics.json"):
        try:
            metric = read(path)
            assert metric["sample_id"] == path.name.removesuffix(".metrics.json")
            metrics[metric["sample_id"]] = (metric, path)
        except (ValueError, OSError, AssertionError) as error:
            audit["corrupt_metrics"].append({"file": relative(path), "error": type(error).__name__})
    definitions = [(s, s["id"], "measurement") for s in samples]
    for request_id, (metric, _) in metrics.items():
        if metric.get("phase") == "warmup":
            base_id = request_id.removeprefix("warmup-")
            sample = next(s for s in samples if s["id"] == base_id)
            definitions.append((sample, request_id, "warmup"))
        elif request_id not in {s["id"] for s in samples}:
            audit["unexpected_metrics"].append(request_id)
    runs = []
    for sample, request_id, phase in definitions:
        metric, path = metrics.get(request_id, ({}, None))
        output_path = RUN / "paddleocr-vl" / f"{request_id}.txt"
        valid = bool(metric) and output_path.exists()
        if valid:
            valid = len(output_path.read_text(encoding="utf-8")) == metric.get("characters")
        if metric:
            assert metric["model"] == "paddleocr-vl" and metric["source"] == sample["source"]
            assert metric["page"] == sample["page"] and metric["phase"] == phase
            assert metric["model_revision"] == protocol["model_revision"]
            assert metric["max_new_tokens"] == protocol["max_new_tokens_per_region"]
        review = region_reviews.get(request_id, {})
        reviewed = isinstance(review.get("degenerate_repetition"), bool)
        technical = int(metric.get("status") == "ok" and not metric.get("hit_token_limit") and valid) if metric else None
        runs.append({"request_id": request_id, "parent_id": sample["parent_id"], "variant": sample["variant"],
            "cohort": "failure4" if sample["parent_id"] in FAILURE_IDS else "control3", "phase": phase,
            "region_index": sample.get("region_index", 0), "region_name": sample.get("region_name", "full_page"),
            "recorded": int(bool(metric)), "status": metric.get("status", "missing_metric"),
            "technical_completed": technical, "token_limit": int(bool(metric.get("hit_token_limit"))) if metric else None,
            "reviewed": int(reviewed), "degenerate_repetition": int(review["degenerate_repetition"]) if reviewed else None,
            "review_notes": review.get("notes"), "seconds": metric.get("seconds"),
            "failed_wall_seconds": metric.get("failed_wall_seconds"), "request_wall_seconds": metric.get("request_wall_seconds"),
            "recognition_or_failed_interval_seconds": metric.get("seconds", metric.get("failed_wall_seconds")),
            "preprocess_seconds": metric.get("preprocess_seconds"), "generation_seconds": metric.get("generation_seconds"),
            "output_tokens": metric.get("output_tokens"), "max_new_tokens": protocol["max_new_tokens_per_region"],
            "peak_allocated_gib": metric.get("peak_allocated_gib"), "peak_reserved_gib": metric.get("peak_reserved_gib"),
            "process_id": metric.get("process_id"), "started_at": metric.get("started_at"), "finished_at": metric.get("finished_at"),
            "load_seconds_per_process": metric.get("load_seconds"), "input_sha256": sample["input_sha256"],
            "timing_valid_for_comparison": int(phase == "measurement" and bool(metric) and request_id not in timing_exclusions),
            "timing_exclusion_reason": timing_exclusions.get(request_id, {}).get("reason", "warmup" if phase == "warmup" else "missing_metric" if not metric else None),
            "output_valid": int(valid), "output_sha256": sha(output_path) if valid else None,
            "metric_file": relative(path) if path else None, "output_file": relative(output_path) if valid else None})
    checks, pages = [], []
    for parent, ref in refs["samples"].items():
        for variant in ("baseline", "split"):
            rows = [r for r in runs if r["parent_id"] == parent and r["variant"] == variant and r["phase"] == "measurement"]
            assert rows
            predicted = predictions.get(variant, {}).get(parent, {})
            all_recorded = all(r["recorded"] for r in rows)
            page_checks = []
            for field, expected in ref["fields"].items():
                reviewed = field in predicted and all_recorded
                value = predicted.get(field)
                check = {"variant": variant, "parent_id": parent, "cohort": rows[0]["cohort"], "field": field,
                    "reference_value": expected, "predicted_value": value, "reviewed": int(reviewed),
                    "exact_match": int(value is not None and normalize(value, ref["normalization"]) == normalize(expected, ref["normalization"])) if reviewed else None,
                    "normalization": ref["normalization"], "reference_status": ref["reference_status"],
                    "blood_value": int(field.startswith("血常规_")),
                    "abnormal_value": int(field.startswith("血常规_") and any(c in expected for c in "↑↓"))}
                page_checks.append(check)
                checks.append(check)
            known_failure = any(r["technical_completed"] == 0 or r["degenerate_repetition"] == 1 for r in rows)
            reviews_ready = all(r["reviewed"] for r in rows)
            completed = 0 if known_failure else 1 if all_recorded and reviews_ready else None
            status = "incomplete" if completed == 0 else "completed" if completed == 1 else "review_pending" if all_recorded else "missing_metric"
            merged = merge_page(variant, parent, rows) if all_recorded else None
            preparation = preparations[parent]["preparation_seconds"] if variant == "split" else None
            if variant == "split":
                assert preparations[parent]["region_count"] == len(rows)
            inference = total(r["recognition_or_failed_interval_seconds"] for r in rows)
            wall = total(r["request_wall_seconds"] for r in rows)
            merge_seconds = merged["merge_seconds"] if merged else None
            pages.append({"parent_id": parent, "variant": variant, "cohort": rows[0]["cohort"],
                "expected_regions": len(rows), "recorded_regions": sum(r["recorded"] for r in rows),
                "completed": completed, "status": status, "review_pending_regions": sum(not r["reviewed"] for r in rows),
                "token_limit_regions": sum(r["token_limit"] or 0 for r in rows),
                "degenerate_regions": sum(r["degenerate_repetition"] or 0 for r in rows),
                "recognition_seconds_sum": inference, "recorded_recognition_seconds_sum": sum(r["recognition_or_failed_interval_seconds"] for r in rows if r["recognition_or_failed_interval_seconds"] is not None),
                "failed_interval_fallback_regions": sum(r["seconds"] is None and r["failed_wall_seconds"] is not None for r in rows),
                "request_wall_seconds_sum": wall, "preparation_seconds": preparation, "merge_seconds": merge_seconds,
                "measured_work_seconds": total([wall, preparation, merge_seconds]), "end_to_end_seconds": None,
                "output_tokens": total(r["output_tokens"] for r in rows),
                "max_page_tokens_budget": sum(r["max_new_tokens"] for r in rows),
                "merged_output_file": merged["output_file"] if merged else None,
                "merged_output_sha256": merged["output_sha256"] if merged else None,
                "timing_valid_for_comparison": int(all(r["timing_valid_for_comparison"] for r in rows)),
                "timing_exclusion_reason": " | ".join(r["timing_exclusion_reason"] for r in rows if r["timing_exclusion_reason"]) or None,
                **field_score(page_checks), "common_complete": 0})
    for page in pages:
        page["common_complete"] = int(all(p["completed"] == 1 for p in pages if p["parent_id"] == page["parent_id"]))
        page["paired_timing_valid"] = int(all(p["timing_valid_for_comparison"] for p in pages if p["parent_id"] == page["parent_id"]))
    summaries = []
    for cohort in ("all7", "failure4", "control3"):
        for variant in ("baseline", "split"):
            selected = [p for p in pages if p["variant"] == variant and (cohort == "all7" or p["cohort"] == cohort)]
            scored = [c for c in checks if c["variant"] == variant and (cohort == "all7" or c["cohort"] == cohort)]
            common = [p for p in selected if p["common_complete"] and p["paired_timing_valid"]]
            timing_valid = [p for p in selected if p["paired_timing_valid"]]
            summaries.append({"cohort": cohort, "variant": variant, "pages_planned": len(selected),
                "recorded_pages": sum(p["recorded_regions"] == p["expected_regions"] for p in selected),
                "completed": sum(p["completed"] == 1 for p in selected), "review_pending": sum(p["completed"] is None for p in selected),
                "token_limit_pages": sum(p["token_limit_regions"] > 0 for p in selected),
                "degenerate_pages": sum(p["degenerate_regions"] > 0 for p in selected),
                "recognition_seconds_sum": total(p["recognition_seconds_sum"] for p in selected),
                "recognition_seconds_mean": average(p["recognition_seconds_sum"] for p in selected),
                "raw_recognition_seconds_sum": total(p["recognition_seconds_sum"] for p in selected),
                "raw_recognition_seconds_mean": average(p["recognition_seconds_sum"] for p in selected),
                "raw_timing_note": "Includes all original timings, including excluded sleep-overlap anomaly; not for speedup claims",
                "paired_timing_valid_pages": len(timing_valid),
                "paired_valid_recognition_seconds_sum": total(p["recognition_seconds_sum"] for p in timing_valid),
                "paired_valid_recognition_seconds_mean": average(p["recognition_seconds_sum"] for p in timing_valid),
                "request_wall_seconds_sum": total(p["request_wall_seconds_sum"] for p in selected),
                "page_wall_mean": average(p["request_wall_seconds_sum"] for p in selected),
                "preparation_seconds_sum": total(p["preparation_seconds"] for p in selected),
                "merge_seconds_sum": total(p["merge_seconds"] for p in selected),
                "common_complete_n": len(common), "common_recognition_mean": average(p["recognition_seconds_sum"] for p in common),
                **field_score(scored), **field_score([c for c in scored if c["blood_value"]], "blood_value"),
                **field_score([c for c in scored if c["abnormal_value"]], "abnormal")})
    recorded = [r for r in runs if r["recorded"]]
    audit.update(planned_requests=17, recorded_requests=sum(r["recorded"] for r in runs if r["phase"] == "measurement"),
                 timing_exclusions=read(exclusion_path) if exclusion_path.exists() else {},
                 recorded_warmups=sum(r["phase"] == "warmup" for r in runs),
                 process_ids=sorted({r["process_id"] for r in recorded}),
                 missing_request_ids=[r["request_id"] for r in runs if not r["recorded"]],
                 invalid_output_ids=[r["request_id"] for r in runs if r["recorded"] and not r["output_valid"]])
    assert len(audit["process_ids"]) <= 1, "Expected a single model process"
    assert len(checks) == 236 and len(pages) == 14
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"exported_at": audit["created_at"], "runs": runs, "pages": pages, "summary": summaries, "checks": checks, "audit": audit}
    (OUT / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("runs", "pages", "summary", "checks"):
        rows = payload[name]
        with (OUT / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (OUT / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "README.md").write_text("""# Paddle 输入改造对照数据

17个正式请求：7整页+10预定义区域；另1预热，单模型单进程。pages是7父页×2方案，summary的all7包含failure4和control3，不可相加计样本。

初轮medical-02整页2802.339秒覆盖已核实Windows睡眠事件（见timing-exclusions.json），原始记录不变，不减去睡眠时长。runs/pages标记timing_valid_for_comparison；paired_timing_valid同时排除这一页两方案，正式同页速度比较只用paired_valid_recognition_seconds_*（全组剩6配对页）或独立timing-recheck，不用raw/旧recognition_seconds_*合计计算提速。准确率保持原7页分母。common_complete_n及common_recognition_mean进一步要求双方完成且计时有效。

recognition_seconds_sum逐页累计所有区域seconds，包含失败/截断，不按区域平均替代页耗时。若失败未产生seconds但有failed_wall_seconds则使用该已测失败区间，failed_interval_fallback_regions标明次数；两者都缺失则总和为空，已有计时保留在recorded_recognition_seconds_sum。request_wall_seconds包含图片读取、预处理传输、生成、解码及原输出写入，排除模型加载、GPU快照、metrics写入。

split preparation_seconds按父页只计一次，含源图读取、EXIF、转正、裁剪、缩小和PNG写入，不含人工选框、hash或缓存PDF渲染。baseline准备时间未知留空。merge_seconds为本exporter首次合并每组固定输出时测得的读取/拼接/写入flush耗时，后续相同输入hash复用merge.metrics.json；不含hash/metadata写入，不执行fsync。合并按固定区域顺序保留全文，仅加两个换行，不按参考筛选或去重。measured_work_seconds仅是有记录操作之和，不是生产端到端延迟；end_to_end_seconds为空。

completed=1要求全部区域技术成功、未截断且全部经过非复读审核；明确失败记0，缺记录或待审核记空并列status。所有页共用冻结的118字段；缺字段且已经审核计错，未核对不计0。field_total始终是固定参考分母，field_reviewed显示审核进度，审核未齐时field_accuracy为空；field_correct保留当前已知正确数。血常规72结果、6带箭头结果是118字段子集，按完整数值+箭头匹配。参考是助手初审，非人工双审或临床审核。

此次干预同时改变人工框、转正、语义路由和有效分辨率；不是隔离单一变量的裁剪实验，也不是官方自动布局pipeline。每区域4096token使多区域页有更大总预算，max_page_tokens_budget/output_tokens明确记录。失败样本为先前观察选择，3张血常规为控制样本，单次测量不可推断普遍性能或置信区间。CSV为UTF-8 BOM，长号码作为文本导入。
""", encoding="utf-8")
    print(json.dumps({"requests_recorded": audit["recorded_requests"], "warmups": audit["recorded_warmups"],
                      "pages": len(pages), "checks": len(checks), "reviewed_fields": sum(c["reviewed"] for c in checks)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
