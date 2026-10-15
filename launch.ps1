param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonCandidates = @(
  "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
  "$env:USERPROFILE\anaconda3\python.exe"
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
$running = $false
try {
  $service = Get-Content -LiteralPath (Join-Path $projectRoot '.local\service.json') -Raw | ConvertFrom-Json
  $secret = (Get-Content -LiteralPath (Join-Path $projectRoot '.local\token') -Raw).Trim()
  $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($service.port)/api/state" -Headers @{Authorization="Bearer $secret"} -TimeoutSec 2
  $running = $true
} catch {}
if (-not $running) {
  $entry = Join-Path $projectRoot 'run.py'
  $localRoot = Join-Path $projectRoot '.local'
  New-Item -ItemType Directory -Path $localRoot -Force | Out-Null
  Start-Process -FilePath $pythonExe -ArgumentList @("`"$entry`"",'serve') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $localRoot 'service.stdout.log') -RedirectStandardError (Join-Path $localRoot 'service.stderr.log')
  for ($attempt=0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Milliseconds 200
    try {
      $service = Get-Content -LiteralPath (Join-Path $projectRoot '.local\service.json') -Raw | ConvertFrom-Json
      $secret = (Get-Content -LiteralPath (Join-Path $projectRoot '.local\token') -Raw).Trim()
      $null = Invoke-RestMethod -Uri "http://127.0.0.1:$($service.port)/api/state" -Headers @{Authorization="Bearer $secret"} -TimeoutSec 1
      $running = $true
      break
    } catch {}
  }
}
if (-not $running) { throw 'Monitor service did not start. Check .local\service.stderr.log.' }
if (-not $NoBrowser) {
  Start-Process -FilePath "http://127.0.0.1:$($service.port)/#token=$secret" -WindowStyle Hidden
}
