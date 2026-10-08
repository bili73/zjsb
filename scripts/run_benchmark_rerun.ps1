$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runDir = Join-Path $projectRoot 'output/benchmark-rerun-20260929'
$attempts = @()
foreach ($model in @('glm-ocr', 'paddleocr-vl', 'chandra')) {
    $pythonPath = Join-Path $projectRoot ".venvs/$model/Scripts/python.exe"
    $arguments = @('-X', 'utf8', '-u', 'scripts/run_ocr_smoke_test.py', '--model', $model, '--run-dir', $runDir, '--warmup', '--record-gpu')
    if ($model -eq 'chandra') { $arguments += @('--quantization', 'int4') }
    $began = Get-Date -Format o
    & $pythonPath @arguments *> (Join-Path $runDir "$model.log")
    $attempts += [ordered]@{model=$model; started_at=$began; finished_at=(Get-Date -Format o); exit_code=$LASTEXITCODE}
    $attempts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'processes.json') -Encoding utf8
}
