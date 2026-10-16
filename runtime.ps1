# Shared runtime detection for ordinary Windows Python installs and Codex bundles.
function Get-MonitorPython {
  $candidates = @("$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
  $command = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($command) { $candidates += $command.Source }
  $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
  if ($launcher) {
    $resolved = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
    if ($LASTEXITCODE -eq 0) { $candidates += [string]$resolved }
  }
  foreach ($candidate in $candidates | Select-Object -Unique) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
    if ($LASTEXITCODE -eq 0) { return $candidate }
  }
  throw 'Python 3.11+ is required. Install Python from python.org with the Python launcher or PATH option enabled.'
}
function Get-MonitorPythonw {
  $python = Get-MonitorPython
  $pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
  if (-not (Test-Path -LiteralPath $pythonw)) { throw 'pythonw.exe is required for the background HUD.' }
  return $pythonw
}
