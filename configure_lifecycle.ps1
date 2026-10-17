$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if (-not (Test-Path -LiteralPath $python)) { throw 'Windowless Python runtime missing.' }
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')
$backup = Join-Path $root ('.local\shortcuts-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $backup | Out-Null
foreach ($folder in @($desktop,$startup)) {
  foreach ($name in @('Codex Monitor.lnk','Codex Monitor Background.lnk','Codex Monitor HUD Settings.lnk','Codex HUD.lnk')) {
    $path = Join-Path $folder $name
    if (Test-Path -LiteralPath $path) {
      $link = $shell.CreateShortcut($path)
      $belongs = $link.Arguments.Contains($root) -or $link.Arguments.Contains('codex-monitor-hud') -or $link.TargetPath.Contains('codex-monitor-hud')
      if (-not $belongs) { throw "Unrelated shortcut: $name" }
      $resolved = (Resolve-Path -LiteralPath $path).Path
      if ([IO.Path]::GetDirectoryName($resolved) -notin @($desktop,$startup)) { throw 'Unexpected shortcut path' }
      Move-Item -LiteralPath $resolved -Destination (Join-Path $backup ((Split-Path $folder -Leaf) + '-' + $name))
    }
  }
}
$oldStartup = Join-Path $startup 'Codex Monitor Lifecycle.lnk'
if (Test-Path -LiteralPath $oldStartup) {
  $old = $shell.CreateShortcut($oldStartup)
  $ours = $old.Arguments.Contains('monitor.lifecycle') -or $old.Arguments.Contains((Join-Path $root 'lifecycle_bootstrap.py'))
  if ($old.TargetPath -ne $python -or -not $ours) { throw 'Unrelated lifecycle shortcut' }
  Move-Item -LiteralPath $oldStartup -Destination (Join-Path $backup 'Lifecycle-startup.lnk')
}
$entry = Join-Path $root 'lifecycle_bootstrap.py'
$link = $shell.CreateShortcut((Join-Path $startup 'Codex Monitor Lifecycle.lnk'))
$link.TargetPath = $python
$link.Arguments = '"' + $entry + '"'
$link.WorkingDirectory = $root
$link.WindowStyle = 7
$link.Save()
Start-Process -FilePath $python -ArgumentList ('"' + $entry + '"') -WorkingDirectory $root -WindowStyle Hidden
Write-Output 'Desktop links moved to backup. Monitors now follow the Codex desktop process.'
