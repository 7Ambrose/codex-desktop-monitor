$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
. (Join-Path $root 'runtime.ps1')
$pythonExe = Get-MonitorPython
& $pythonExe (Join-Path $root 'tools\check_install.py')
if ($LASTEXITCODE -ne 0) { throw 'Check the Python, Node.js and official Codex requirements in RELEASE.md.' }
if (-not (Test-Path -LiteralPath (Join-Path $env:USERPROFILE 'plugins\codex-monitor-hud\scripts\start.ps1'))) {
  throw 'Install the optional HUD first using the instructions in RELEASE.md, then run this installer again.'
}
& $pythonExe (Join-Path $root 'configure.py') install
if ($LASTEXITCODE -ne 0) { throw 'Codex configuration installation failed.' }
& (Join-Path $root 'install_hud_shortcut.ps1')
if (Test-Path -LiteralPath (Join-Path $root 'assets\monitor.ico')) { & (Join-Path $root 'install_desktop.ps1') }
Write-Output 'Monitor installed with hidden desktop lifecycle integration.'
