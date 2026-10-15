param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$serviceFile = Join-Path $PSScriptRoot '.local\service.json'
if (Test-Path -LiteralPath $serviceFile) {
  $service = Get-Content -LiteralPath $serviceFile -Raw | ConvertFrom-Json
  $process = Get-Process -Id $service.pid -ErrorAction SilentlyContinue
  if ($process) {
    $recordedStart = [DateTimeOffset]::FromUnixTimeSeconds([long][Math]::Floor($service.started)).UtcDateTime
    $delta = [Math]::Abs(($process.StartTime.ToUniversalTime() - $recordedStart).TotalSeconds)
    if ($process.ProcessName -notmatch '^python(w)?$' -or $delta -gt 8) {
      throw 'Process identity does not match this monitor. Nothing was stopped.'
    }
    Stop-Process -Id $process.Id
    $process.WaitForExit(5000) | Out-Null
  }
}
& (Join-Path $PSScriptRoot 'launch.ps1') -NoBrowser:$NoBrowser
