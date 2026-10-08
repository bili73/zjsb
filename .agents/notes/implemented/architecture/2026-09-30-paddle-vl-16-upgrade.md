# Agent Note: Install and qualify Paddle 1.6 while retaining the working default

Status: implemented
Scope: backend/model_worker.py, backend/ocr_app/config.py, scripts, tests, RUNTIME.md, IMPLEMENTATION_PLAN.md
Last-verified: 2026-09-30

## Problem

The installed PaddlePaddle/PaddleOCR-VL checkpoint is the original v1 release, revision 7fa00a8c55b735ba51ba49a9058f3f9c57a99a11, using Transformers 4.57.6 remote code. Official PaddleOCR-VL-1.5 and 1.6 supersede it; 0.9B denotes the parameter scale rather than a release number. The user authorizes replacement and continued paired experiments. Changing weights without changing the loader risks treating dependency failures as model regressions.

## Decision

PaddlePaddle/PaddleOCR-VL-1.6 is installed at pinned revision c5630abae1d940eafe0697512a0325494b02ab42 in models/paddleocr-vl-1.6 and a separate .venvs/paddleocr-vl-1.6 environment with native Transformers 5.17.0 and Torch 2.10.0+cu128. Original weights, environment, references and measurements remain intact. The private worker accepts an explicit checkpoint within the two supported Paddle releases; its default remains the original checkpoint for reproducible legacy experiments. Production keeps the public paddleocr_vl key and v1 checkpoint/environment because this deployment's provisional medical comparison shows stable regression. Recognizer installation does not implement the official full-page layout pipeline.

Old and new raw OCR use the same references, prompts and token budgets, with default-resolution and matched-resolution runs labelled separately. The seven-input dual extraction diagnostic also repeats with new Paddle and unchanged GLM/template. Each run retains separate failures, generation outcomes, complete serial paired costs and unavailable confidence. GPU accuracy work uses one resident model at a time; only the explicitly authorized production smoke probe retains both resident with serial loading/inference.

## Decision audit

The default-size probe reveals numeric-content changes in seven unique blood-result fields. The v1 processor allows 2,822,400 pixels; 1.6 defaults to 1,003,520. A separate paired diagnostic raises only experimental 1.6 to the old profile (min 147,384 / max 2,822,400), retaining thumbnails and reference/budget semantics. Its strict scores also lose seven unique fields, but a subsequent source-preserving audit distinguishes six explicit LaTeX arrow-format differences from one true numeric-content change. The previous assertion that all seven remain arrow-to-digit errors after pixel matching was incorrect; strict scores and original outputs remain unchanged. The [mapping repair](../../implemented/bug-fix/2026-09-30-evidence-bound-field-mapping.md) owns supported-format parsing and its independent replay. Synthetic warmup retains checkpoint defaults and is labelled separately. The [OTSL defect](../bug-fix/2026-09-30-paddle-otsl-table-decoding.md) is repaired independently; initial no-adapter scores remain retained. The [whole-folder diagnostic](../testing/2026-09-30-whole-medical-corpus.md) expands the convenience sample without claiming new held-out evidence.

The [lifecycle decision](../../implemented/architecture/2026-09-29-local-dual-model-lifecycle.md) owns residency and cleanup and is partially overlapping, not superseded. The [dual diagnostic](../../implemented/testing/2026-09-30-dual-certificate-extraction.md) owns fusion and frozen reference semantics and is partially overlapping, not superseded. The schema, durable-task and diagnostics notes retain their own contracts. Existing notes do not select a newer Paddle checkpoint; no rejected upgrade proposal exists. This decision replaces installed-version facts, not the dual-resident strategy or production review gate.

## Alternatives considered

- Overwriting the original checkpoint saves disk and avoids new paths. It removes a working rollback and contaminates comparisons, so releases use distinct directories.
- Updating the original Transformers environment avoids duplicate packages. It can break the original remote-code adapter and GLM-independent baseline, so the new environment stays isolated.
- Deploying the full official Paddle pipeline adds layout and newer spotting capabilities. It changes multiple recognition stages at once; the present comparison upgrades only the recognizer and preserves the current region pipeline.
- Selecting 1.5 first reduces the distance from the original release. Official 1.6 is available and uses native Transformers support; test that release directly and retain the original for fallback.

## Testing

- Offline load/warmup, 56-call seven-input dual extraction and both 12-call medical pixel profiles complete with EOS and confirmed owned exits; dependency versions and model revision are recorded.
- New Paddle raw rules score 20/78 certificate-field instances (old 22/78) and 4/6 bank-card numbers (old 2/6). Revised-template combined certificate paths do not surpass the original single-GLM template.
- Both medical profiles strictly score old 144/144 versus new 130/144. A first-repeat format audit reproduces the stored scores: default profile has seven numeric-content changes; matched profile has one numeric-content change and six explicit arrow-format differences. These are different failure mechanisms, not seven repeated numeric errors. Neither profile proves a universal weight regression because loader/preprocessor backends still differ.
- Matched-profile average old/new request times are 24.015/22.543 seconds; allocator peaks 2.719/2.587 GiB; sampled process RSS peaks 1.782/1.828 GiB. All figures are selected-page diagnostics, not HR requirements.
- 135 CPU tests pass, including checkpoint-family/path rejection. Default runtime dual-resident smoke starts in 14.266 seconds, correctly recognizes all three synthetic calls and confirms process handles signal after shutdown. The [report and CSV links](../../../../output/paddle16-upgrade-20260930/REPORT.md) preserve failures and limits.
- The subsequent 66-page/image corpus completes 82 physical inferences per checkpoint. Its distinct, single-round blood subset scores 72/72 versus 66/72; native-table reference consistency improves from 51/95 to 64/95, and physical generation timeouts decrease from seven to two. The newer model is not uniformly inferior; these gains do not justify exchanging verified blood-value errors for a version-only upgrade. Reference bases and datasets remain separate.

## Consequences

Native Transformers checkpoint selection is available, but the application default deliberately remains v1. Later weights can regress in this deployment even if general benchmarks improve. The small convenience sample does not qualify population accuracy, full report coverage or 16 GB HR machines. Loader changes confound weight-only attribution; processor defaults differ. Separate environments cost disk space and upkeep but preserve rollback. Installation/download costs remain separate from application loading/inference time. Further adoption needs positive evidence rather than a version-number assumption.
