$ErrorActionPreference = 'Stop'
$pythonw = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { throw 'Python runtime not found.' }
$taskName = 'CodexMonitorLifecycle'
$bootstrap = Join-Path $PSScriptRoot 'lifecycle_bootstrap.py'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and ($existing.Actions.Arguments -notcontains ('"' + $bootstrap + '"'))) {
  throw 'Scheduled task belongs to another application.'
}
$action = New-ScheduledTaskAction -Execute $pythonw -Argument ('"' + $bootstrap + '"') -WorkingDirectory $PSScriptRoot
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Keep the Codex monitoring HUD running while Codex is open.' -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$name = 'Codex HUD.lnk'
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
$launcher = Join-Path $PSScriptRoot 'launch_hud.py'
if (Test-Path -LiteralPath $path) {
  $old = $shell.CreateShortcut($path)
  if (-not $old.Arguments.Contains($launcher)) { throw 'Shortcut belongs to another application.' }
}
$link = $shell.CreateShortcut($path)
$link.TargetPath = $pythonw
$link.Arguments = '"' + $launcher + '"'
$link.WorkingDirectory = $PSScriptRoot
$link.IconLocation = (Join-Path $PSScriptRoot 'assets\monitor.ico') + ',0'
$link.WindowStyle = 7
$link.Description = 'Open the compact Codex monitoring HUD'
$link.Save()
Start-ScheduledTask -TaskName $taskName
Write-Output 'HUD shortcut created; independent lifecycle task started.'
