"""Small Windows watcher: run monitors only while the Codex desktop is present."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from .reviewer import find_codex

ROOT = Path(__file__).resolve().parent.parent
HUD = Path.home() / 'plugins/codex-monitor-hud'
STATE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CodexMonitorHUD'


def processes():
    class Entry(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
                    ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
                    ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD), ('name', w.WCHAR * 260)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.OpenProcess.restype = w.HANDLE
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise OSError('Cannot inspect desktop process state')
    result = []
    try:
        entry = Entry(); entry.size = ctypes.sizeof(entry)
        found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if entry.name.lower() in ('chatgpt.exe', 'codex.exe'):
                handle = kernel.OpenProcess(0x1000, False, entry.pid)
                if handle:
                    try:
                        size = w.DWORD(32768); path = ctypes.create_unicode_buffer(size.value)
                        if kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                            result.append((entry.pid, path.value))
                    finally:
                        kernel.CloseHandle(handle)
            found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return result


def is_desktop(path):
    path = path.replace('/', '\\').lower()
    return ((path.endswith('\\chatgpt.exe') and '\\windowsapps\\openai.codex_' in path)
            or (path.endswith('\\codex.exe') and '\\openai\\codex\\app\\' in path))


def start_monitors():
    subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                    '-File', str(ROOT / 'launch.ps1'), '-NoBrowser'],
                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=25, check=True)
    heartbeat = STATE / 'hud.heartbeat'
    if HUD.exists() and not (heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < 15):
        env = hud_environment()
        for name in ('exit.signal', 'manual-exit.signal'):
            (STATE / name).unlink(missing_ok=True)
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(HUD / 'scripts/start.ps1')],
                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=15, check=True, env=env)


def hud_environment():
    # Upstream asks for codex.cmd; Desktop ships codex.exe outside the user PATH.
    # Scope this adapter to the HUD child process, without changing system PATH.
    executable = find_codex()
    shim = ROOT / '.local/hud-bin'
    shim.mkdir(parents=True, exist_ok=True)
    (shim / 'codex.cmd').write_text('@echo off\n"' + executable + '" %*\n', encoding='utf-8')
    env = os.environ.copy()
    env['PATH'] = str(shim) + os.pathsep + env.get('PATH', '')
    return env


def stop_monitors():
    if STATE.exists():
        (STATE / 'exit.signal').write_text('desktop closed', encoding='utf-8')
    record = ROOT / '.local/service.json'
    if not record.exists():
        return
    info = json.loads(record.read_text())
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = w.HANDLE
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1001, False, int(info['pid']))
    if not handle:
        return
    try:
        created, exited, system, user = (w.FILETIME() for _ in range(4))
        size = w.DWORD(32768); path = ctypes.create_unicode_buffer(size.value)
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(system), ctypes.byref(user)):
            return
        if not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            return
        started = ((created.dwHighDateTime << 32) + created.dwLowDateTime) / 10000000 - 11644473600
        if Path(path.value).name.lower() in ('python.exe', 'pythonw.exe') and abs(started - info['started']) < 8:
            kernel.TerminateProcess(handle, 0)
    finally:
        kernel.CloseHandle(handle)


def main():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = w.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
    mutex = kernel.CreateMutexW(None, False, 'Local\\CodexMonitor-' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:16])
    if not mutex or ctypes.get_last_error() == 183:
        return
    running = False; absent_since = None
    while True:
        try:
            present = any(is_desktop(path) for _, path in processes())
            if present:
                absent_since = None
                if not running:
                    start_monitors(); running = True
            elif running:
                absent_since = absent_since or time.monotonic()
                if time.monotonic() - absent_since >= 15:
                    stop_monitors(); running = False
            (ROOT / '.local/lifecycle.json').write_text(json.dumps({'pid': os.getpid(), 'desktop_present': present, 'monitors_active': running, 'at': time.time()}))
        except Exception as exc:
            (ROOT / '.local/lifecycle-error.txt').write_text(type(exc).__name__, encoding='utf-8')
        time.sleep(5)


if __name__ == '__main__':
    main()
