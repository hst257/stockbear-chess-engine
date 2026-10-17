$ErrorActionPreference = 'Stop'
# Execute only when ready to continue the remaining frozen games.
$marker = Join-Path $PSScriptRoot 'STOP_REQUESTED'
if (Test-Path -LiteralPath $marker) { Remove-Item -LiteralPath $marker }
& (Join-Path $PSScriptRoot 'start_tournament.ps1') -Resume
