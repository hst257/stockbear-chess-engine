param([int]$MaximumSeconds = 5400, [int]$IntervalSeconds = 5)
$ErrorActionPreference = 'Stop'
$destination = Join-Path $PSScriptRoot 'cpu0-counters.jsonl'
$deadline = (Get-Date).AddSeconds($MaximumSeconds)
$metadata = @{
    started_utc = (Get-Date).ToUniversalTime().ToString('o')
    method = 'Windows formatted Processor Information counters, logical CPU0 (0,0); diagnostic snapshots, not per-search frequency measurements'
    warning = 'ProcessorFrequency may report nominal MHz. Do not substitute it for effective frequency. PercentProcessorPerformance is retained as a reported counter without an independently calibrated MHz conversion. Limit flags are reported values, not proof of thermal causation.'
    interval_seconds = $IntervalSeconds
    source = 'https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters'
}
$metadata | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'cpu0-telemetry-method.json') -Encoding utf8
while ((Get-Date) -lt $deadline) {
    $began = Get-Date
    try {
        $counter = Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation |
            Where-Object { $_.Name -eq '0,0' } |
            Select-Object Name, ProcessorFrequency, PercentProcessorPerformance, PercentPerformanceLimit,
                PercentofMaximumFrequency, PercentProcessorUtility, PercentProcessorTime, PerformanceLimitFlags, ProcessorStateFlags
        @{timestamp_utc = $began.ToUniversalTime().ToString('o'); counter = $counter;
          query_seconds = ((Get-Date) - $began).TotalSeconds} |
            ConvertTo-Json -Compress -Depth 5 | Add-Content -LiteralPath $destination -Encoding utf8
    } catch {
        @{timestamp_utc = $began.ToUniversalTime().ToString('o'); error = $_.Exception.Message} |
            ConvertTo-Json -Compress | Add-Content -LiteralPath $destination -Encoding utf8
    }
    $progress = Get-Content -Raw -LiteralPath (Join-Path $PSScriptRoot 'progress.json') | ConvertFrom-Json
    if ($progress.completed_searches -eq $progress.expected_searches) { break }
    Start-Sleep -Seconds $IntervalSeconds
}
