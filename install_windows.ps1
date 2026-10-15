$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pythonCandidates = @(
  "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
  "$env:USERPROFILE\anaconda3\python.exe"
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
& $pythonExe (Join-Path $root 'configure.py') install
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration installation failed.' }
& (Join-Path $root 'configure_lifecycle.ps1')
if (Test-Path -LiteralPath (Join-Path $root 'assets\monitor.ico')) { & (Join-Path $root 'install_desktop.ps1') }
Write-Output 'Monitor installed with hidden desktop lifecycle integration.'
