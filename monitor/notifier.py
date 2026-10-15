import base64
import html
import os
import subprocess
import threading


def notify(reason):
    """Best effort native Windows notification; never blocks task processing."""
    if os.name != 'nt':
        return
    title=html.escape('Codex 任务需要处理')
    body=html.escape(reason[:180]+'。请打开任务监控查看依据。')
    xml=f'<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual></toast>'
    xml64=base64.b64encode(xml.encode('utf-8')).decode('ascii')
    code=("$ErrorActionPreference='Stop';"
          "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;"
          "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]>$null;"
          "$doc=New-Object Windows.Data.Xml.Dom.XmlDocument;"
          f"$doc.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{xml64}')));"
          "$toast=[Windows.UI.Notifications.ToastNotification]::new($doc);"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.WindowsPowerShell').Show($toast)")
    encoded=base64.b64encode(code.encode('utf-16le')).decode('ascii')
    def deliver():
        try:
            subprocess.run([os.path.join(os.environ['SystemRoot'],'System32/WindowsPowerShell/v1.0/powershell.exe'),
                            '-NoProfile','-NonInteractive','-EncodedCommand',encoded],
                           creationflags=subprocess.CREATE_NO_WINDOW,stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,timeout=12)
        except (OSError,subprocess.TimeoutExpired):
            pass
    threading.Thread(target=deliver,daemon=True,name='notice').start()
