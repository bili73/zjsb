"""Export observed OCR measurements; provisional text coverage is not accuracy."""

import csv
import hashlib
import json
import re
import statistics
from datetime import datetime
from pathlib import Path

from summarize_certificate_batch import compact

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output/benchmark-data"
MODELS = ["glm-ocr", "paddleocr-vl", "chandra"]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_csv(name, rows):
    with (OUT / name).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j-1] + (a != b)))
        previous = current
    return previous[-1]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reference_path = ROOT / "output/certificate-batch/review-reference.json"
    reference = read_json(reference_path)
    refs = {r["id"]: r for r in reference["samples"]}
    bank_reference = read_json(ROOT / "output/bankcard-baseline/review-reference.json")
    bank_refs = {r["id"]: r for r in bank_reference["samples"]}
    bank_predictions = read_json(ROOT / "output/bankcard-baseline/card-predictions.json")
    predictions = {(r["batch"], r["model"], r["sample_id"]): r for r in bank_predictions}
    runs, checks, card_checks = [], [], []
    for batch in ["certificate-batch", "smoke-test", "bankcard-baseline", "bankcard-crop"]:
        base = ROOT / "output" / batch
        samples = {s["id"]: s for s in read_json(base / "inputs/manifest.json")}
        for model in MODELS:
            for path in sorted((base / model).glob("*.metrics.json")):
                metric = read_json(path)
                sid = metric["sample_id"]
                sample = samples[sid]
                assert metric["model"] == model and metric["source"] == sample["source"]
                raw_path = path.with_name(f"{sid}.txt")
                raw = raw_path.read_text(encoding="utf-8")
                assert "\x00" not in raw, f"Corrupt OCR output: {raw_path}"
                assert len(raw) == metric["characters"], f"Output length mismatch: {raw_path}"
                completed = int(metric["status"] == "ok" and not metric["hit_token_limit"])
                medical = sid.startswith("medical-")
                is_bank = batch.startswith("bankcard-")
                doc_type = "bank_card" if is_bank else "medical_report" if medical else "education_document"
                ref = refs.get(sid) if batch == "certificate-batch" else None
                row = {
                    "batch": batch, "model": model, "sample_id": sid,
                    "document_type": doc_type,
                    "common10": int(batch == "certificate-batch" and sid in refs),
                    "completed": completed, "status": metric["status"],
                    "truncated": int(metric["hit_token_limit"]),
                    "elapsed_s": metric["seconds"], "output_tokens": metric["output_tokens"],
                    "tokens_per_elapsed_s": metric["output_tokens"] / metric["seconds"],
                    "peak_allocated_gib": metric["peak_allocated_gib"],
                    "peak_reserved_gib": metric["peak_reserved_gib"],
                    "load_s_per_process": metric["load_seconds"],
                    "precision": "NF4/BF16 compute" if model == "chandra" else "BF16",
                    "torch_threads": metric.get("torch_threads"),
                    "input_width_px": metric["input_size"][0],
                    "input_height_px": metric["input_size"][1],
                    "max_new_tokens": metric["max_new_tokens"],
                    "task": sample["task"], "page": metric["page"],
                    "model_revision": metric["model_revision"],
                    **{k + "_version": v for k, v in metric["versions"].items()},
                    "source_sha256": sample.get("source_sha256") or hashlib.sha256(Path(sample["source"]).read_bytes()).hexdigest(),
                    "input_sha256": hashlib.sha256(Path(sample["image"]).read_bytes()).hexdigest(),
                    "source": metric["source"],
                    "metric_file": path.relative_to(ROOT).as_posix(),
                    "output_file": raw_path.relative_to(ROOT).as_posix(),
                    "metric_recovered_from_log": int(batch == "certificate-batch" and model == "chandra" and sid == "cert-034-p1"),
                    "reference_status": bank_reference["status"] if is_bank else reference["status"] if ref else "not_annotated",
                    "field_accuracy": None, "character_error_rate": None,
                    "word_error_rate": None,
                }
                runs.append(row)
                if is_bank:
                    annotated = predictions[(batch, model, sid)]
                    raw_card = annotated["raw_card_text"]
                    assert compact(raw_card) in compact(raw), f"Prediction not found in OCR: {path}"
                    predicted = re.sub(r"\s+", "", raw_card)
                    expected = bank_refs[sid]["card_number"]
                    distance = edit_distance(predicted, expected)
                    card_checks.append({"batch": batch, "model": model, "sample_id": sid,
                        "bank_name": bank_refs[sid]["bank_name"], "reference_card_number": expected,
                        "predicted_card_number": predicted, "exact_match": int(predicted == expected),
                        "edit_distance": distance, "reference_digit_count": len(expected),
                        "card_number_cer": distance / len(expected),
                        "reference_status": bank_reference["status"], "raw_card_text": raw_card,
                        "prediction_selection": "assistant_selected_card_number_span_from_raw_output",
                        "output_file": row["output_file"]})
                if ref:
                    for field, expected in ref["checks"].items():
                        checks.append({
                            "batch": batch, "model": model, "sample_id": sid,
                            "field": field, "reference_text": expected,
                            "reference_found": int(compact(expected) in compact(raw)),
                            "run_completed": completed,
                            "reference_status": reference["status"],
                            "reference_source": reference_path.relative_to(ROOT).as_posix(),
                            "output_file": row["output_file"],
                        })

    summaries = []
    for batch, cohort in [("certificate-batch", "all_available"), ("certificate-batch", "common10"),
                          ("smoke-test", "education_document"), ("smoke-test", "medical_report"),
                          ("bankcard-baseline", "all_available"), ("bankcard-crop", "all_available")]:
        for model in MODELS:
            selected = [r for r in runs if r["batch"] == batch and r["model"] == model
                        and (cohort == "all_available" or (cohort == "common10" and r["common10"])
                             or r["document_type"] == cohort)]
            times = [r["elapsed_s"] for r in selected]
            complete_times = [r["elapsed_s"] for r in selected if r["completed"]]
            # Coverage is reported only for the explicitly annotated common cohort.
            fields = [f for f in checks if f["model"] == model] if cohort == "common10" else []
            cards = [c for c in card_checks if c['batch'] == batch and c['model'] == model]
            summaries.append({
                "batch": batch, "cohort": cohort, "model": model,
                "attempted": len(selected), "completed": len(complete_times),
                "truncated": sum(r["truncated"] for r in selected),
                "errors_or_empty": sum(r["status"] != "ok" for r in selected),
                "completion_rate": len(complete_times) / len(selected),
                "elapsed_total_s": sum(times), "elapsed_mean_s": statistics.mean(times),
                "elapsed_median_s": statistics.median(times),
                "elapsed_p90_s": percentile(times, .9),
                "completed_elapsed_median_s": statistics.median(complete_times) if complete_times else None,
                "max_allocated_gib": max(r["peak_allocated_gib"] for r in selected),
                "max_reserved_gib": max(r["peak_reserved_gib"] for r in selected),
                "reference_found_count": sum(f["reference_found"] for f in fields) if fields else None,
                "reference_check_count": len(fields) if fields else None,
                "provisional_text_coverage": sum(f["reference_found"] for f in fields) / len(fields) if fields else None,
                "field_accuracy": None, "character_error_rate": None, "word_error_rate": None,
                "card_exact_match_count": sum(c['exact_match'] for c in cards) if cards else None,
                "card_reference_count": len(cards) if cards else None,
                "provisional_card_exact_match_rate": sum(c['exact_match'] for c in cards) / len(cards) if cards else None,
                "provisional_card_number_cer": sum(c['edit_distance'] for c in cards) / sum(c['reference_digit_count'] for c in cards) if cards else None,
            })

    excluded = []
    for path in sorted((ROOT / "output/smoke-test/paddleocr-vl/failed-transformers-4.57.6").glob("*.metrics.json")):
        m = read_json(path)
        excluded.append({"model": m["model"], "sample_id": m["sample_id"], "status": m["status"],
                         "error": m.get("error"), "exclusion_reason": "pre_compatibility_fix_no_completed_inference",
                         "metric_file": path.relative_to(ROOT).as_posix()})
    excluded.append({"model": "chandra", "sample_id": "bank-002-p1", "status": "startup_failed",
                     "error": "Process exited with code 1 during weight loading; no traceback or sample metric was saved; cause unknown",
                     "exclusion_reason": "no_sample_inference_measurement_before_retry",
                     "metric_file": "output/bankcard-crop/chandra-run.log"})
    assert len(runs) == 99 and len(checks) == 114 and len(card_checks) == 12
    assert len({(r['batch'], r['model'], r['sample_id']) for r in runs}) == len(runs)
    assert all(sum(r['common10'] for r in runs if r['model'] == m) == 10 for m in MODELS)
    assert sum(r['truncated'] for r in runs) == 4
    assert all(r['field_accuracy'] is None for r in runs)
    for name, data in [("runs.csv", runs), ("model_summary.csv", summaries),
                       ("field_checks.csv", checks), ("bankcard_checks.csv", card_checks), ("excluded_attempts.csv", excluded)]:
        write_csv(name, data)
    payload = {"exported_at": datetime.now().astimezone().isoformat(),
               "runs": runs, "summary": summaries, "field_checks": checks, "bankcard_checks": card_checks, "excluded_attempts": excluded}
    (OUT / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(runs), "field_checks": len(checks), "excluded_attempts": len(excluded),
                      "common10": [s for s in summaries if s['cohort'] == 'common10']}, indent=2))


if __name__ == "__main__":
    main()
