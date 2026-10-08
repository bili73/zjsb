"""Run an installed checkpoint offline on the local smoke-test images."""

import argparse
import importlib.metadata
import json
import os
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["HF_HOME"] = str(ROOT / ".cache" / "huggingface")
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["DO_NOT_TRACK"] = "1"


def gpu_snapshot():
    snapshot = {"captured_at": datetime.now().astimezone().isoformat()}
    for key, query in [("device", "--query-gpu=name,memory.used,utilization.gpu,temperature.gpu"),
                       ("processes", "--query-compute-apps=pid,process_name")]:
        try:
            result = subprocess.run(["nvidia-smi", query, "--format=csv,noheader"], capture_output=True, text=True, timeout=10)
            snapshot[key] = result.stdout.strip()
            if result.returncode:
                snapshot[key + "_error"] = result.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as error:
            snapshot[key + "_error"] = str(error)
    return snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["glm-ocr", "paddleocr-vl", "chandra"], required=True)
    parser.add_argument("--sample", default="all")
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--quantization", choices=["none", "int4"], default="none")
    parser.add_argument("--run-dir", type=Path, default=ROOT / "output/smoke-test")
    parser.add_argument("--warmup", action="store_true", help="Save one untimed-for-summary warmup before selected inputs")
    parser.add_argument("--record-gpu", action="store_true", help="Capture GPU state outside each measured interval")
    args = parser.parse_args()

    import torch
    torch.set_num_threads(4)
    from PIL import Image
    from transformers import AutoModelForCausalLM, AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

    output = args.run_dir.resolve() / args.model
    output.mkdir(parents=True, exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable; this test requires the configured NVIDIA GPU.")
    manifest = json.loads((args.run_dir / "inputs/manifest.json").read_text(encoding="utf-8"))
    selected_ids = set(args.sample.split(","))
    samples = [s for s in manifest if args.sample == "all" or s["id"] in selected_ids]
    if args.sample != "all" and selected_ids - {s["id"] for s in samples}:
        raise ValueError(f"Unknown sample IDs: {selected_ids - {s['id'] for s in samples}}")
    if not samples:
        raise ValueError(f"Unknown sample: {args.sample}")
    if args.warmup:
        samples = [{**samples[0], "id": "warmup-" + samples[0]["id"], "phase": "warmup"}] + samples
    checkpoint = ROOT / "models" / args.model
    versions = {name: importlib.metadata.version(name) for name in ["torch", "torchvision", "transformers", "accelerate"]}
    print(json.dumps({"model": args.model, "gpu": torch.cuda.get_device_name(), "versions": versions}, ensure_ascii=False), flush=True)
    started = time.perf_counter()
    kwargs = {"local_files_only": True, "torch_dtype": torch.bfloat16, "attn_implementation": "sdpa"}
    if args.quantization == "int4":
        kwargs["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["device_map"] = {"": 0}
    if args.model == "paddleocr-vl":
        model = AutoModelForCausalLM.from_pretrained(checkpoint, trust_remote_code=True, **kwargs).eval()
        # This pinned checkpoint uses the old keyword; Transformers 4.57.6 expects input_embeds.
        module = importlib.import_module(model.__class__.__module__)
        original_create_causal_mask = module.create_causal_mask

        def compatible_create_causal_mask(*, inputs_embeds, **mask_kwargs):
            return original_create_causal_mask(input_embeds=inputs_embeds, **mask_kwargs)

        module.create_causal_mask = compatible_create_causal_mask
        processor = AutoProcessor.from_pretrained(checkpoint, trust_remote_code=True, local_files_only=True)
    else:
        model = AutoModelForImageTextToText.from_pretrained(checkpoint, **kwargs).eval()
        processor = AutoProcessor.from_pretrained(checkpoint, local_files_only=True)
    load_seconds = time.perf_counter() - started
    print(f"Model loaded in {load_seconds:.1f}s", flush=True)

    failures = 0
    for sample in samples:
        result = {"model": args.model, "sample_id": sample["id"], "source": sample["source"], "page": sample["page"], "versions": versions, "quantization": args.quantization, "torch_threads": torch.get_num_threads(), "load_seconds": round(load_seconds, 3), "model_revision": json.loads((checkpoint / "download_manifest.json").read_text())["revision"], "max_new_tokens": args.max_new_tokens}
        result.update(phase=sample.get("phase", "measurement"), started_at=datetime.now().astimezone().isoformat(), gpu_name=torch.cuda.get_device_name(), process_id=os.getpid())
        if args.record_gpu:
            result["gpu_before"] = gpu_snapshot()
        print(f"Running {sample['id']}", flush=True)
        if args.model == "paddleocr-vl":
            result["compatibility_patch"] = "create_causal_mask: inputs_embeds -> input_embeds"
        inference_started = None
        request_started = time.perf_counter()
        try:
            image = Image.open(sample["image"]).convert("RGB")
            image.thumbnail((1600, 1600))
            result["input_size"] = list(image.size)
            if args.model == "chandra":
                from chandra.prompts import PROMPT_MAPPING
                prompt = PROMPT_MAPPING["ocr_layout"]
            elif args.model == "glm-ocr":
                prompt = "Table Recognition:" if sample["task"] == "table" else "Text Recognition:"
            else:
                prompt = "Table Recognition:" if sample["task"] == "table" else "OCR:"
            messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            started = time.perf_counter()
            inference_started = started
            inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt").to("cuda")
            torch.cuda.synchronize()
            preprocessing_done = time.perf_counter()
            generation_kwargs = {"max_new_tokens": args.max_new_tokens, "do_sample": False, "use_cache": True}
            if args.model == "chandra":
                eos = model.generation_config.eos_token_id
                eos = [eos] if isinstance(eos, int) else list(eos or [])
                im_end = processor.tokenizer.convert_tokens_to_ids("<|im_end|>")
                if im_end is not None and im_end not in eos:
                    eos.append(im_end)
                generation_kwargs["eos_token_id"] = eos
            with torch.inference_mode():
                generated = model.generate(**inputs, **generation_kwargs)
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - started
            new_tokens = generated[0, inputs["input_ids"].shape[1]:]
            raw = processor.decode(new_tokens, skip_special_tokens=True)
            (output / f"{sample['id']}.txt").write_text(raw, encoding="utf-8")
            result.update({"status": "ok" if raw.strip() else "empty", "seconds": round(elapsed, 3), "output_tokens": len(new_tokens), "hit_token_limit": len(new_tokens) >= args.max_new_tokens, "peak_allocated_gib": round(torch.cuda.max_memory_allocated() / 1024**3, 3), "peak_reserved_gib": round(torch.cuda.max_memory_reserved() / 1024**3, 3), "characters": len(raw)})
            result.update(preprocess_seconds=round(preprocessing_done-started, 6), generation_seconds=round(elapsed-(preprocessing_done-started), 6))
            if args.model == "chandra":
                from chandra.output import extract_images, parse_chunks, parse_html, parse_markdown
                chunks = parse_chunks(raw, image)
                (output / f"{sample['id']}.html").write_text(parse_html(raw, include_headers_footers=True), encoding="utf-8")
                (output / f"{sample['id']}.md").write_text(parse_markdown(raw, include_headers_footers=True), encoding="utf-8")
                (output / f"{sample['id']}.chunks.json").write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
                for name, crop in extract_images(raw, chunks, image).items():
                    crop.save(output / name)
            if not raw.strip() or result["hit_token_limit"]:
                failures += 1
            del inputs, generated, new_tokens
        except Exception as error:
            failures += 1
            result.update({"status": "error", "error": str(error), "traceback": traceback.format_exc()})
            if inference_started is not None and "seconds" not in result:
                result["failed_wall_seconds"] = round(time.perf_counter()-inference_started, 3)
        result["request_wall_seconds"] = round(time.perf_counter()-request_started, 6)
        result["request_wall_scope"] = "image_read+preprocess+transfer+generation+decode+output_write; excludes model_load, GPU_snapshots, metrics_write"
        result["finished_at"] = datetime.now().astimezone().isoformat()
        if args.record_gpu:
            result["gpu_after"] = gpu_snapshot()
        metrics_path = output / f"{sample['id']}.metrics.json"
        temporary_path = metrics_path.with_suffix(".json.tmp")
        with temporary_path.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(metrics_path)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        torch.cuda.empty_cache()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
