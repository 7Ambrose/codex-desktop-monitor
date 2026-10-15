"""Sample idle service CPU and Windows process memory; no model requests."""
import ctypes
from ctypes import wintypes
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from monitor.server import settings,token


def state():
    req=urllib.request.Request(f"http://127.0.0.1:{settings()['port']}/api/state",headers={'Authorization':'Bearer '+token()})
    with urllib.request.urlopen(req,timeout=3) as response:return json.load(response)


def memory(pid):
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD),('PeakWorkingSetSize',ctypes.c_size_t),
                  ('WorkingSetSize',ctypes.c_size_t),('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                  ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                  ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    handle=kernel.OpenProcess(0x410,False,pid)
    if not handle:return None
    try:
        info=Counters();info.cb=ctypes.sizeof(info)
        if not psapi.GetProcessMemoryInfo(handle,ctypes.byref(info),info.cb):return None
        return round(info.WorkingSetSize/1048576,1)
    finally:kernel.CloseHandle(handle)


start=state();wall=time.monotonic()
time.sleep(10)
end=state();elapsed=time.monotonic()-wall
pid=json.loads((ROOT/'.local/service.json').read_text())['pid']
result={'sample_seconds':round(elapsed,2),'service_single_core_cpu_percent':round(100*(end['process_cpu_seconds']-start['process_cpu_seconds'])/elapsed,3),
        'service_working_set_mib':memory(pid),'scope':'Python service only; excludes browser, Codex and brief notification processes'}
(ROOT/'.local/resource-measurement.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
