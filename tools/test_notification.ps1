$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null
[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]>$null
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.WindowsPowerShell')
Write-Output ('Windows notification permission: ' + $notifier.Setting)
if ($null -ne $notifier.Setting -and $notifier.Setting.ToString() -ne 'Enabled') { throw 'Windows has disabled notifications for this sender.' }
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml('<toast><visual><binding template="ToastGeneric"><text>Codex monitor</text><text>Notification test: abnormal tasks will request your attention.</text></binding></visual></toast>')
$notifier.Show([Windows.UI.Notifications.ToastNotification]::new($doc))
Write-Output 'Test notification submitted successfully; focus mode can still suppress the banner.'
