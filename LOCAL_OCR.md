# 本地 OCR 测试环境

本项目用于比较 Chandra OCR 2、GLM-OCR 和原版 PaddleOCR-VL-0.9B。
输入文件、模型推理和输出结果均在本机处理。下载模型与安装依赖需要联网；推理脚本强制使用本地权重及离线模式。

本轮样本的人工抽查记录见 [REVIEW.md](output/smoke-test/REVIEW.md)。

## 环境与模型

| 模型 | Python 环境 | 权重目录 | 测试接口 |
| --- | --- | --- | --- |
| GLM-OCR | `.venvs/glm-ocr` | `models/glm-ocr` | Transformers 核心模型 |
| PaddleOCR-VL-0.9B | `.venvs/paddleocr-vl` | `models/paddleocr-vl` | 官方 Transformers 核心模型，非完整版面解析流水线 |
| Chandra OCR 2 | `.venvs/chandra` | `models/chandra` | Transformers + Chandra 的提示词及结果解析 |

证件照片自动摆正使用的 CPU 方向模型（PP-LCNet doc-ori，`models/pp-lcnet-doc-ori`，经 `scripts/download_image_upright_model.py` 安装并 SHA256 核验）与 `.venvs/image-upright`、`.venvs/paddleocr-vl-1.6` 离线对照环境不参与上表三模型对照，见 `RUNTIME.md` 证件照片自动摆正章节与 `scripts/IMAGE-UPRIGHT-NOTICES.md`。

模型下载来源及 commit revision 保存在各目录的 `download_manifest.json`。
环境依赖版本保存在 `requirements-*.lock.txt`。GPU 运行时使用 PyTorch CUDA wheel，无需另外安装完整 CUDA Toolkit。

本机使用 Windows、Python 3.12.14、RTX 3060 12 GB，以及 PyTorch 2.10.0+cu128。
GLM 和 Chandra 使用 Transformers 5.17.0；原版 Paddle 使用独立环境中的 Transformers 4.57.6。
Paddle 固定版本的模型代码调用 `create_causal_mask(inputs_embeds=...)`，与该 Transformers 的 `input_embeds` 参数名不一致。
测试脚本仅在内存中适配这个参数名，并写入结果的 `compatibility_patch`；下载的模型代码及权重保持原样。

## 运行已有样本

在 PowerShell 中进入项目：

```powershell
Set-Location 'E:\work\OCR_shibie'
& '.\.venvs\glm-ocr\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model glm-ocr
& '.\.venvs\paddleocr-vl\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model paddleocr-vl
& '.\.venvs\chandra\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model chandra --quantization int4
```

逐个运行，等待一个进程退出后再启动另一个，避免 12 GB 显存争用。
可以附加 `--sample certificate`、`--sample medical-page-04` 或 `--sample medical-page-12` 只运行一张。
多个样本 ID 可以用英文逗号连接，例如 `--sample cert-001-p1,cert-003-p1`。

输入清单：`output/smoke-test/inputs/manifest.json`，包含源文件路径、PDF 物理页码和任务类型。
输出目录：`output/smoke-test/<model>/`。

- `*.txt`：模型生成的原始文本，不包含输入提示词。
- `*.metrics.json`：模型版本、量化方式、推理耗时、输出 token 数、显存峰值和截断状态。
- Chandra 另外输出 `*.html`、`*.md` 和 `*.chunks.json`，保留版面块与坐标；识别出的图片块另外保存为 WebP。

峰值显存是 PyTorch 当前进程的分配/预留量，不等于整个显卡的系统占用。
`seconds` 包括图像预处理和生成，不包括模型加载。首次运行还可能包含内核初始化开销。
达到 token 上限时会标记 `hit_token_limit: true` 并返回非零退出码，不能把截断输出视为完整识别。
本机 Chandra 使用 NF4 量化、BF16 计算；没有安装 `causal_conv1d` 和 `flash-linear-attention`，相关操作使用 PyTorch 回退实现。
因此本轮耗时不能代表优化部署后的速度，也不能用于三模型的严格性能排名。

## 更换测试材料

```powershell
& '.\.venvs\glm-ocr\Scripts\python.exe' -X utf8 scripts\prepare_smoke_inputs.py --report '完整体检报告.pdf' --certificate '证书图片.jpg'
```

当前准备脚本专用于本轮报告，提取 PDF 物理第 4、12 页，并准备一张证书图片。
换其他报告时需要先确定正确页码。运行会覆盖本轮输入清单及同名输出，因此应先保存需要保留的旧结果。

## 评估边界

这是一组安装后的功能检查，不是准确率基准。三个模型的任务提示词和输出格式不同，不能只按耗时或是否输出 JSON 判定优劣。
Paddle 使用元素识别接口处理输入；整页表现不能直接代表带版面检测的完整 PaddleOCR 流水线表现。
报告原始数值、名称、单位和来源应保留；本轮不执行医学诊断、异常分级或录用决策。

Chandra 代码与模型权重许可证不同，企业使用前需按其 `models/chandra/LICENSE` 核实适用条件。
GLM-OCR 和 PaddleOCR-VL 的许可证随官方权重保留。用户材料及结果已加入 `.gitignore`，不应提交到代码仓库。

## 扩充证书测试

本轮将 `F:\dingding\附件_20260728` 的 34 个文件准备为 34 个图像输入，保存于 `output/certificate-batch/`。
GLM/Paddle 跑全量；Chandra 对照样本的 ID 记录在 `review-reference.json`，其中包含原图初步核对值及不确定项。
该核对表未经人工双审，不应当作正式金标准。封面、学历截图、一图多证分别记录；文件名不作为字段答案。

```powershell
& '.\.venvs\glm-ocr\Scripts\python.exe' -X utf8 scripts\prepare_certificate_samples.py --source 'F:\dingding\附件_20260728'
& '.\.venvs\glm-ocr\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model glm-ocr --run-dir output/certificate-batch
& '.\.venvs\paddleocr-vl\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model paddleocr-vl --run-dir output/certificate-batch
$certificateIds = (Get-Content -Raw -Encoding utf8 output/certificate-batch/review-reference.json | ConvertFrom-Json).samples.id -join ','
& '.\.venvs\chandra\Scripts\python.exe' -X utf8 -u scripts\run_ocr_smoke_test.py --model chandra --quantization int4 --run-dir output/certificate-batch --sample $certificateIds
& '.\.venvs\glm-ocr\Scripts\python.exe' -X utf8 scripts\summarize_certificate_batch.py
```

`inputs/inventory.json` 保留原文件哈希、EXIF 方向和读取状态。只校正 EXIF 方向并等比缩图，没有主动检测证书朝向或裁掉黑边。
`review-images/` 是供视觉核对使用的裁剪/旋转图，不作为本轮推理输入。
重复运行会覆盖当前批次同名文件；本轮批次与上一轮 `smoke-test` 相互独立。

- [图文对照页面](output/certificate-batch/comparison.html)：点击原图、展开各模型原文。
- [批次报告](output/certificate-batch/REVIEW.md)：范围、实测情况、错误与限制。
- `summary.json` / `reference-checks.csv`：运行汇总和核对字符串出现情况；字符串出现不代表字段归属正确。

## 统一实测数据

- [统计口径与数据字典](output/benchmark-data/README.md)
- [模型汇总 CSV](output/benchmark-data/model_summary.csv)、[逐次推理 CSV](output/benchmark-data/runs.csv)
- [证书字符串核对](output/benchmark-data/field_checks.csv)、[银行卡完整号码核对](output/benchmark-data/bankcard_checks.csv)
- [Excel 工作簿](outputs/01a0e741-2881-71e0-9d30-b7b4caecde0a/OCR实测数据.xlsx)

正式准确率字段暂空。证书字符串覆盖和银行卡初步整号匹配分别记录，不混为同一种准确率。

## 银行卡测试

3 张原图保存在 `output/bankcard-baseline/`，失败的恒丰银行卡另做一次手动旋转、裁剪、放大诊断，保存在 `output/bankcard-crop/`。原文件未修改。
准备原图：`scripts/prepare_certificate_samples.py --source F:\dingding\附件_按类型_20260929\银行卡照片 --output output/bankcard-baseline/inputs --prefix bank`。
诊断裁剪脚本为 `scripts/prepare_bankcard_crop.py`，坐标只适用于本张卡，不能作为自动卡片检测器。
运行方式沿用 `scripts/run_ocr_smoke_test.py --model ... --run-dir output/bankcard-baseline`；裁剪版使用 `--run-dir output/bankcard-crop`，Chandra 加 `--quantization int4`。
