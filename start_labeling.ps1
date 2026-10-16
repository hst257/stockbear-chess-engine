[CmdletBinding()]
param(
    [ValidateSet('run', 'status', 'validate', 'export', 'prepare')]
    [string]$Mode = 'run',
    [string]$InputDirectory,
    [string]$OutputDirectory,
    [string]$Stockfish,
    [string]$Python,
    [string[]]$ExistingCorpus,
    [int]$Nodes,
    [int]$Threads,
    [int]$Workers,
    [int]$HashMB,
    [int]$Limit,
    [int]$PositionsPerGame,
    [int]$MinPly,
    [int]$MaxPly,
    [int]$PlyGap,
    [int]$Seed,
    [double]$Timeout,
    [double]$ProgressSeconds,
    [string]$Encoding,
    [string]$Destination,
    [ValidateSet('v2', 'v3-full', 'v3-bucket16')]
    [string]$Features = 'v2',
    [switch]$Resume,
    [switch]$FastResume,
    [int]$ExecutionWorkers,
    [switch]$CheckResume,
    [switch]$DryRun,
    [switch]$RetryFailed,
    [switch]$AllowPartial
)
$ErrorActionPreference = 'Stop'
$trainingRoot = Join-Path $PSScriptRoot 'StockBear_NNUE_training'
if (-not $Python) {
    foreach ($candidate in @('.venv\Scripts\python.exe', '.venv-labeling\Scripts\python.exe')) {
        $candidatePath = Join-Path $trainingRoot $candidate
        if (Test-Path -LiteralPath $candidatePath) { $Python = $candidatePath; break }
    }
    if (-not $Python) { throw 'Python environment missing. See LABELING_README.md, or provide -Python.' }
}
$pythonCommand = (Get-Command $Python -ErrorAction Stop).Source
$labelingModule = 'stockbear.labeling'
if ($FastResume -or $CheckResume -or $PSBoundParameters.ContainsKey('ExecutionWorkers')) {
    if (-not $Resume -or $Mode -ne 'run') { throw 'Fast execution options require -Resume and -Mode run.' }
    $labelingModule = 'stockbear.labeling_runtime'
}
$cliArguments = @('-u', '-m', $labelingModule, $Mode)
$mapping = @{
    InputDirectory='--input'; OutputDirectory='--output'; Stockfish='--stockfish';
    Nodes='--nodes'; Threads='--threads'; Workers='--workers'; HashMB='--hash-mb'; Limit='--limit';
    PositionsPerGame='--positions-per-game'; MinPly='--min-ply'; MaxPly='--max-ply';
    PlyGap='--ply-gap'; Seed='--seed'; Timeout='--timeout'; ProgressSeconds='--progress-seconds';
    Encoding='--encoding'; Destination='--destination'; Features='--features'
}
# Resolve user paths before switching directories; quoted paths remain individual arguments.
$pathParameters = @('InputDirectory','OutputDirectory','Stockfish','Destination')
foreach ($key in $mapping.Keys) {
    if ($PSBoundParameters.ContainsKey($key)) {
        $value = $PSBoundParameters[$key]
        if ($pathParameters -contains $key) {
            $value = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($value)
        }
        $cliArguments += @($mapping[$key], [string]$value)
    }
}
foreach ($path in $ExistingCorpus) {
    $cliArguments += @('--existing-corpus', $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($path))
}
if ($Resume) { $cliArguments += '--resume' }
if ($DryRun) { $cliArguments += '--dry-run' }
if ($RetryFailed) { $cliArguments += '--retry-failed' }
if ($AllowPartial) { $cliArguments += '--allow-partial' }
if ($PSBoundParameters.ContainsKey('ExecutionWorkers')) { $cliArguments += @('--execution-workers', [string]$ExecutionWorkers) }
if ($CheckResume) { $cliArguments += '--check-resume' }
Push-Location -LiteralPath $trainingRoot
try {
    & $pythonCommand @cliArguments
    $labelingExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $labelingExitCode
