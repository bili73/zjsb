"""Export rerun measurements and reviewed field accuracy; never runs inference."""
import csv
import hashlib
import json
import re
import statistics
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/benchmark-rerun-data"
MODELS = ("glm-ocr", "paddleocr-vl", "chandra")
SESSIONS = ("benchmark-rerun-20260929", "benchmark-resume-20260929", "medical-expansion-20260929")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm(value, rule="whitespace_only"):
    value = str(value)
    if rule.startswith("nfkc"):
        value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"\s+", "", value)
    if rule.endswith("ignore_prose_punctuation"):
        value = "".join(c for c in value if not unicodedata.category(c).startswith("P"))
    return value


def stats(values):
    return {"n": len(values), "mean_s": statistics.mean(values) if values else None,
            "median_s": statistics.median(values) if values else None,
            "total_s": sum(values)}


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(rows)


def references():
    refs = {}
    for kind, path in [("certificate", ROOT / "output/certificate-batch/review-reference.json"),
                       ("bankcard", ROOT / "output/bankcard-baseline/review-reference.json")]:
        data = read(path)
        for sample in data["samples"]:
            fields = sample["checks"] if kind == "certificate" else {"卡号": sample["card_number"]}
            entry = (fields, data["status"], path.relative_to(ROOT).as_posix())
            refs[("rerun", sample["id"])] = entry
            if kind == "bankcard":
                refs[("rerun", "crop-" + sample["id"])] = entry
    path = ROOT / "output/benchmark-rerun-20260929/medical-reference.json"
    if path.exists():
        data = read(path)
        refs[("rerun", data["sample_id"])] = (data["checks"], data["status"], path.relative_to(ROOT).as_posix())
    path = ROOT / "output/medical-expansion-20260929/references.json"
    if path.exists():
        data = read(path)
        for sid, sample in data["samples"].items():
            refs[("medical_expansion", sid)] = (sample["fields"], sample.get("reference_status", "provisional"), path.relative_to(ROOT).as_posix())
    return refs


def predictions():
    values = {}
    for session in SESSIONS:
        base = ROOT / "output" / session
        batch = "medical_expansion" if session.startswith("medical-expansion") else "rerun"
        for path in sorted(base.glob("*reviewed-predictions*.json")):
            data = read(path)
            models = data.get("models", {data.get("model"): data.get("predictions", {})})
            for model, samples in models.items():
                for sid, fields in samples.items():
                    for field, value in fields.items():
                        key = (batch, model, sid, field)
                        if key in values and values[key][0] != value:
                            raise ValueError(f"Conflicting reviewed prediction: {key}")
                        values[key] = (value, path.relative_to(ROOT).as_posix())
    return values


def collect():
    runs, planned, hash_checks, invalid = [], {}, [], []
    for session in SESSIONS:
        base = ROOT / "output" / session
        manifest_path = base / "inputs/manifest.json"
        if not manifest_path.exists():
            continue
        batch = "medical_expansion" if session.startswith("medical-expansion") else "rerun"
        manifest = {s["id"]: s for s in read(manifest_path)}
        for sid, sample in manifest.items():
            actual_hash = hashlib.sha256(Path(sample["image"]).read_bytes()).hexdigest()
            expected_hash = sample.get("input_sha256")
            hash_checks.append({"session": session, "sample_id": sid, "sha256": actual_hash,
                                "manifest_hash_matches": actual_hash == expected_hash if expected_hash else None})
            assert not expected_hash or actual_hash == expected_hash, f"Input hash mismatch: {sid}"
            key = (batch, sid)
            if key in planned:
                assert planned[key]["input_sha256"] == actual_hash, f"Resume input changed: {sid}"
            group = sample.get("page_kind", "medical_report") if batch == "medical_expansion" else sample["group"]
            planned[key] = {**sample, "input_sha256": actual_hash, "group": group,
                            "case_group": sample.get("group") if batch == "medical_expansion" else None}
        for model in MODELS:
            for path in sorted((base / model).glob("*.metrics.json")):
                try:
                    metric = read(path)
                except (ValueError, OSError) as error:
                    invalid.append({"path": path.relative_to(ROOT).as_posix(), "error": type(error).__name__})
                    continue
                sid = metric["sample_id"]
                phase = metric.get("phase", "measurement")
                original_id = sid.removeprefix("warmup-") if phase == "warmup" else sid
                sample = manifest[original_id]
                assert metric["model"] == model and metric["source"] == sample["source"]
                assert metric["page"] == sample["page"]
                raw_path = path.with_name(sid + ".txt")
                output_valid = raw_path.exists()
                if output_valid and "characters" in metric:
                    output_valid = len(raw_path.read_text(encoding="utf-8")) == metric["characters"]
                complete = metric.get("status") == "ok" and not metric.get("hit_token_limit") and output_valid
                external = set()
                snapshot_errors = []
                for side in ("gpu_before", "gpu_after"):
                    snapshot = metric.get(side, {})
                    if not snapshot:
                        snapshot_errors.append(side + ":missing")
                    snapshot_errors.extend(side + ":" + k for k in snapshot if k.endswith("_error"))
                    for line in snapshot.get("processes", "").splitlines():
                        pid, _, process = line.partition(",")
                        if pid.strip() != str(metric.get("process_id")) and re.search(r"python|llama|ollama|vllm|triton", process, re.I):
                            external.add(process.strip())
                runs.append({"batch": batch, "session": session, "group": planned[(batch, original_id)]["group"],
                    "case_group": planned[(batch, original_id)]["case_group"], "page_kind": sample.get("page_kind"),
                    "model": model, "sample_id": original_id, "phase": phase,
                    "status": metric.get("status"), "completed": int(complete),
                    "truncated": int(bool(metric.get("hit_token_limit"))), "output_valid": int(output_valid),
                    "elapsed_s": metric.get("seconds"), "failed_wall_s": metric.get("failed_wall_seconds"),
                    "preprocess_s": metric.get("preprocess_seconds"), "generation_s": metric.get("generation_seconds"),
                    "output_tokens": metric.get("output_tokens"), "max_new_tokens": metric.get("max_new_tokens"),
                    "peak_allocated_gib": metric.get("peak_allocated_gib"), "peak_reserved_gib": metric.get("peak_reserved_gib"),
                    "load_s_per_process": metric.get("load_seconds"), "process_id": metric.get("process_id"),
                    "started_at": metric.get("started_at"), "finished_at": metric.get("finished_at"),
                    "precision": "NF4/BF16 compute" if model == "chandra" else "BF16",
                    "torch_threads": metric.get("torch_threads"), "model_revision": metric.get("model_revision"),
                    "input_sha256": planned[(batch, original_id)]["input_sha256"],
                    "external_inference_process_candidates": " | ".join(sorted(external)),
                    "snapshot_errors": " | ".join(snapshot_errors),
                    "metric_file": path.relative_to(ROOT).as_posix(), "output_file": raw_path.relative_to(ROOT).as_posix(),
                    "selected_measurement": 0, "common_complete": 0})
    selected = {}
    for row in runs:
        if row["phase"] != "measurement":
            continue
        key = (row["batch"], row["model"], row["sample_id"])
        # Never silently choose among completed repeat measurements.
        assert key not in selected, f"Duplicate recorded measurement: {key}"
        selected[key] = row
        row["selected_measurement"] = 1
    return runs, planned, selected, hash_checks, invalid


def main():
    runs, planned, selected, hashes, invalid = collect()
    refs, preds = references(), predictions()
    checks, summaries, missing = [], [], []
    # Completeness is a sample property across models, independent of summary grouping.
    for (batch, model, sid), row in selected.items():
        row["common_complete"] = int(all(selected.get((batch, other, sid), {}).get("completed") for other in MODELS))
    for (batch, sid), sample in planned.items():
        ref_fields, status, ref_path = refs.get((batch, sid), ({}, "not_annotated", ""))
        for model in MODELS:
            row = selected.get((batch, model, sid))
            if row is None:
                missing.append({"batch": batch, "model": model, "sample_id": sid})
            for field, expected in ref_fields.items():
                key = (batch, model, sid, field)
                reviewed = key in preds and row is not None
                value, pred_path = preds.get(key, (None, ""))
                normalization = "whitespace_only"
                if batch == "medical_expansion":
                    normalization = "nfkc_whitespace"
                    if field.startswith("总检_") or field == "超声提示":
                        normalization += "_ignore_prose_punctuation"
                checks.append({"batch": batch, "group": sample["group"], "model": model, "sample_id": sid,
                    "field": field, "reference_value": expected, "predicted_value": value,
                    "normalization": normalization,
                    "reviewed": int(reviewed), "exact_match": int(value is not None and norm(value, normalization) == norm(expected, normalization)) if reviewed else None,
                    "prediction_missing": int(value is None) if reviewed else None,
                    "reference_status": status, "reference_file": ref_path, "prediction_file": pred_path,
                    "run_completed": row["completed"] if row else None})
    for row in runs:
        annotated = [c for c in checks if c["batch"] == row["batch"] and c["model"] == row["model"]
                     and c["sample_id"] == row["sample_id"]] if row["selected_measurement"] else []
        scored = [c for c in annotated if c["reviewed"]]
        row.update(reference_fields=len(annotated) if annotated else None,
                   unreviewed_fields=len(annotated)-len(scored) if annotated else None,
                   field_correct=sum(c["exact_match"] for c in scored) if scored else None,
                   field_total=len(scored) if scored else None,
                   field_accuracy=sum(c["exact_match"] for c in scored)/len(scored) if scored else None)
    groups = {(b, s["group"]) for (b, _), s in planned.items()}
    if any(b == "medical_expansion" for b, _ in planned):
        groups.add(("medical_expansion", "all_selected"))
    for batch, group in sorted(groups):
        ids = {sid for (b, sid), sample in planned.items() if b == batch and (group == "all_selected" or sample["group"] == group)}
        common = {sid for sid in ids if all(selected.get((batch, model, sid), {}).get("completed") for model in MODELS)}
        for model in MODELS:
            rows = [selected[(batch, model, sid)] for sid in ids if (batch, model, sid) in selected]
            finished = [r for r in rows if r["completed"]]
            paired = [r["elapsed_s"] for r in rows if r["sample_id"] in common]
            annotated = [c for c in checks if c["batch"] == batch and c["sample_id"] in ids and c["model"] == model]
            scored = [c for c in annotated if c["reviewed"]]
            summary = {"batch": batch, "group": group, "model": model, "planned": len(ids),
                "recorded": len(rows), "missing_metrics": len(ids)-len(rows), "completed": len(finished),
                "truncated": sum(r["truncated"] for r in rows),
                "errors_or_invalid_output": sum(not r["completed"] and not r["truncated"] for r in rows),
                "completion_rate_all_planned": len(finished)/len(ids),
                "completion_rate_recorded": len(finished)/len(rows) if rows else None,
                "truncated_elapsed_s": sum(r["elapsed_s"] or 0 for r in rows if r["truncated"]),
                "common_sample_ids": " | ".join(sorted(common)),
                **{"common_completed_"+k:v for k,v in stats(paired).items()},
                **{"own_completed_"+k:v for k,v in stats([r["elapsed_s"] for r in finished]).items()},
                "reference_fields": len(annotated), "reviewed_fields": len(scored),
                "unreviewed_fields": len(annotated)-len(scored),
                "correct_fields": sum(c["exact_match"] for c in scored) if scored else None,
                "provisional_field_accuracy": sum(c["exact_match"] for c in scored)/len(scored) if scored else None,
                "max_allocated_gib": max((r["peak_allocated_gib"] for r in rows if r["peak_allocated_gib"] is not None), default=None),
                "sessions": " | ".join(sorted({r["session"] for r in rows}))}
            summaries.append(summary)
            for label, subset in [("blood_results", [c for c in scored if c["field"].startswith("血常规_")]),
                                  ("blood_abnormal_results", [c for c in scored if c["field"].startswith("血常规_") and any(a in c["reference_value"] for a in "↑↓")])]:
                summary[label+"_reviewed"] = len(subset)
                summary[label+"_correct"] = sum(c["exact_match"] for c in subset) if subset else None
                summary[label+"_accuracy"] = sum(c["exact_match"] for c in subset)/len(subset) if subset else None
            summary.update(attempted=summary["recorded"], comparable_n=summary["common_completed_n"],
                           comparable_mean_s=summary["common_completed_mean_s"], comparable_median_s=summary["common_completed_median_s"],
                           field_correct=summary["correct_fields"], field_total=summary["reviewed_fields"],
                           field_accuracy=summary["provisional_field_accuracy"])
    overlaps = []
    for i, left in enumerate(runs):
        for right in runs[i+1:]:
            if left["model"] == right["model"] or not all(r.get("started_at") and r.get("finished_at") for r in (left, right)):
                continue
            if max(left["started_at"], right["started_at"]) < min(left["finished_at"], right["finished_at"]):
                overlaps.append([left["metric_file"], right["metric_file"]])
    audit = {"created_at": datetime.now().astimezone().isoformat(), "input_hash_checks": hashes,
        "missing_measurements": missing, "invalid_metric_files": invalid,
        "cross_model_recorded_interval_overlaps": overlaps,
        "external_inference_candidates": [{"metric_file": r["metric_file"], "processes": r["external_inference_process_candidates"]} for r in runs if r["external_inference_process_candidates"]],
        "warmup_counts": {s:{m:sum(r["session"]==s and r["model"]==m and r["phase"]=="warmup" for r in runs) for m in MODELS} for s in SESSIONS},
        "notes": ["Hashes are checked at export against manifest; per-sample inference-time hashes were not captured.",
                  "GPU process snapshots are endpoint observations, not continuous isolation proof.",
                  "Token-limit records have completed generation and 4096 tokens; absent records after reboot are missing, not token-limit truncations.",
                  "seconds includes processor, host-to-GPU transfer and generation; excludes loading, image IO, decoding, writing and snapshots.",
                  "started_at/finished_at intervals additionally contain snapshots and output work; overlap test is conservative.",
                  "All measurements are single repeats; resume results are a different process/session."]}
    interrupted_missing = ["medical-page-12", "bank-001-p1", "bank-002-p1", "bank-003-p1", "crop-bank-002-p1"]
    audit["interrupted_sessions"] = [{"session": "benchmark-rerun-20260929", "model": "chandra",
        "reason": "computer_restart_reported_by_user", "evidence_scope": "user report; no elapsed-time reconstruction",
        "missing_at_interruption": interrupted_missing, "interrupted_elapsed_s": None,
        "resume_session": "benchmark-resume-20260929",
        "resumed_recorded_sample_ids": [sid for sid in interrupted_missing
            if selected.get(("rerun", "chandra", sid), {}).get("session") == "benchmark-resume-20260929"]}]
    audit["interrupted_sessions"].append({
        "session": "medical-expansion-20260929", "model": "chandra",
        "reason": "system_reboot_during_model_startup",
        "started_at": "2026-09-29T11:51:40.4052215+08:00",
        "next_boot_at": "2026-09-29T11:52:30.5+08:00",
        "evidence_scope": "queue stdout and Win32_OperatingSystem.LastBootUpTime; exact crash time and cause unassigned",
        "interrupted_elapsed_s": None,
        "missing_at_interruption": [sid for (batch, sid) in planned if batch == "medical_expansion"],
        "measurement_records_before_interruption": 0,
    })
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, rows in [("runs.csv", runs), ("summary.csv", summaries), ("checks.csv", checks)]:
        write_csv(OUT / filename, rows)
    payload = {"exported_at": audit["created_at"], "runs": runs, "summary": summaries, "checks": checks, "audit": audit}
    (OUT / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    note = """# OCR 重测数据说明

CSV 为 UTF-8 BOM；长编号按文本导入。旧 benchmark-data 不修改。

- runs：每次落盘记录一行，保留 warmup、截断及 session；selected_measurement=1 才是正式测量。
- runs 的 field_correct/field_total/field_accuracy 来自该次正式测量已核对字段；未标注、未核对及预热均留空，reference_fields/unreviewed_fields 另列。中断而未落盘的耗时未知，audit 中为 null，不填0；恢复会话独立标识。
- summary：按 batch/group/model 汇总。画速度对比用 common_completed_mean_s / median_s，三模型仅使用共同完成的相同输入；own_completed 只作单模型观察。
- 截断耗时保留于 runs 和 truncated_elapsed_s，不进入正常速度。完成率分母同时列全部计划数与已落盘数；missing_metrics 单列，不伪装成完成或截断。
- checks：对应原图参考和已审核 OCR 实际字段值。旧批次仅去空白；新增医疗按参考规则 NFKC+去空白，总检结论及超声提示额外忽略标点，逐行 normalization 明示。结果数字及异常箭头不修正，繁简字不转换。null 预测且 reviewed=1 表示已核对确实缺失，计错；未核对/未落盘 exact_match 留空。
- provisional_field_accuracy = correct_fields / reviewed_fields；reference_fields、unreviewed_fields 展示覆盖范围。截断记录中仍逐字段评分，避免仅保留成功样本的准确率偏差。参考由助手目视初审，未经人工双审，只代表列出的字段，不是全文/整份报告准确率，也不评价医学结论。
- 字段由助手从 OCR 输出定位后评分，尚未衡量自动键值抽取的成功率。表格项目名称或缩写拼写不单独评分；上下文能唯一定位对应结果列时，按结果值计分。
- 新增医疗按 page_kind 分血常规/结论/长图汇总，case_group 留在明细；all_selected 是7输入总览，不能再和子组相加。血常规结果及异常结果准确率是总字段的子集。原银行卡与人工转正裁剪卡分组，不当作独立卡片累计。
- elapsed_s 排除模型加载、文件读取/解码/保存、GPU 快照；包括 processor、传输和生成。load_s_per_process 在记录中重复，禁止按行求和。
- 单次测量，无置信区间；Chandra 为 NF4/BF16 compute，另两模型 BF16，输出格式和长度不同。GPU 快照无法排除两个端点之间短暂出现的其他任务。
"""
    (OUT / "README.md").write_text(note, encoding="utf-8")
    audit_base = ROOT / "output/benchmark-rerun-20260929"
    (audit_base / "timing-audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    audit_md = f"# 计时审计\n\n已落盘 {len(runs)} 条（含预热）；计划中未落盘 {len(missing)} 条；损坏 JSON {len(invalid)} 个。\n\n跨模型记录区间重叠 {len(overlaps)} 对；GPU 端点快照中其他推理进程候选 {len(audit['external_inference_candidates'])} 条。\n\n" + "\n".join("- " + n for n in audit["notes"])
    (audit_base / "timing-audit.md").write_text(audit_md + "\n", encoding="utf-8")
    print(json.dumps({"runs":len(runs), "checks":len(checks), "missing":len(missing), "invalid":len(invalid), "overlaps":len(overlaps), "external_candidates":len(audit["external_inference_candidates"])}, ensure_ascii=True))


if __name__ == "__main__":
    main()
