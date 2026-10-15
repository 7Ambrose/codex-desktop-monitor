$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$name = 'Codex ' + [char]0x76D1 + [char]0x63A7 + '.lnk'
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
$launcher = Join-Path $PSScriptRoot 'launch.ps1'
if (Test-Path -LiteralPath $path) {
  $old = $shell.CreateShortcut($path)
  if (-not $old.Arguments.Contains($launcher)) { throw 'Shortcut belongs to another application.' }
}
$link = $shell.CreateShortcut($path)
$link.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$link.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $launcher + '"'
$link.WorkingDirectory = $PSScriptRoot
$link.IconLocation = (Join-Path $PSScriptRoot 'assets\monitor.ico') + ',0'
$link.WindowStyle = 7
$link.Description = 'Open local Codex task monitoring dashboard'
$link.Save()
Write-Output 'One dashboard shortcut created with a custom icon.'
