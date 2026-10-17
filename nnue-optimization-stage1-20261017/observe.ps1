param([string]$Output = 'nnue-optimization-stage1-20261017/environment.json')
$taskBefore = Get-Process | Select-Object Id,ProcessName,CPU
Start-Sleep -Seconds 3
$taskAfter = Get-Process | Select-Object Id,ProcessName,CPU
$taskLoads = foreach ($taskProcess in $taskAfter) {
    $taskOld = $taskBefore | Where-Object Id -EQ $taskProcess.Id
    if ($taskOld -and $taskProcess.CPU -gt $taskOld.CPU) {
        [pscustomobject]@{
            name = $taskProcess.ProcessName
            pid = $taskProcess.Id
            cpu_percent = [math]::Round(($taskProcess.CPU-$taskOld.CPU)/3/12*100,2)
        }
    }
}
[ordered]@{
    timestamp = (Get-Date -Format o)
    power = (powercfg /getactivescheme | Out-String)
    battery = (Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus | Select-Object PowerOnline,Charging,Discharging)
    cpu = (Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)
    frequency_snapshot = (Get-CimInstance Win32_PerfFormattedData_Counters_ProcessorInformation | Where-Object Name -EQ '_Total' | Select-Object ProcessorFrequency,PercentofMaximumFrequency,PercentProcessorTime)
    thermal = 'No usable ACPI temperature telemetry in preceding profile; no temperature or throttling claim'
    nitrosense = 'Quiet / Eco, last user-confirmed setting; not exposed through Windows power scheme'
    top_process_cpu_3sec = ($taskLoads | Sort-Object cpu_percent -Descending | Select-Object -First 12)
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Output
