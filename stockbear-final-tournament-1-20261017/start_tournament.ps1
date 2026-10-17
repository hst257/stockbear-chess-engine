param([switch]$Resume)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'launch.py'
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'preflight.json'))) { throw 'Run freeze and preflight first.' }
if ($Resume) { & $python $script --resume } else { & $python $script }
if ($LASTEXITCODE -ne 0) { throw "Standalone launcher failed ($LASTEXITCODE)" }
