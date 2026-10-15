param(
    [ValidateSet('dual_resident')][string]$Mode,
    [int]$Port = 8765,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$appPython = Join-Path $PSScriptRoot '.venvs/app/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $appPython)) { throw 'Application environment missing. See RUNTIME.md.' }
$launchArgs = @('-u', '-X', 'utf8', (Join-Path $PSScriptRoot 'backend/launch.py'), '--port', "$Port")
if ($Mode) { $launchArgs += @('--mode', $Mode) }
if ($NoBrowser) { $launchArgs += '--no-browser' }
& $appPython @launchArgs
exit $LASTEXITCODE
