$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$pythonCandidates = @(
  "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
  "$env:USERPROFILE\anaconda3\python.exe"
)
$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { $pythonExe = (Get-Command python -ErrorAction Stop).Source }
$launcher = Join-Path $root 'launch.ps1'
$shell = New-Object -ComObject WScript.Shell
$desktopPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'Codex Monitor.lnk'
$startupPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'Codex Monitor Background.lnk'
foreach ($target in @($desktopPath, $startupPath)) {
  if (Test-Path -LiteralPath $target) {
    $existing = $shell.CreateShortcut($target)
    if (-not $existing.Arguments.Contains($launcher)) { throw 'An unrelated shortcut already exists. No shortcut was replaced.' }
  }
}
& $pythonExe (Join-Path $root 'configure.py') install
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration installation failed.' }
foreach ($target in @($desktopPath, $startupPath)) {
  $link = $shell.CreateShortcut($target)
  $link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcher`""
  if ($target -eq $startupPath) { $link.Arguments += ' -NoBrowser' }
  $link.WorkingDirectory = $root
  $link.WindowStyle = 7
  $link.Description = 'Local Codex task monitor'
  $link.Save()
}
& (Join-Path $root 'restart.ps1') -NoBrowser
Write-Output 'Monitor configuration, desktop entry and login startup are installed.'
