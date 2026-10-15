"""Keep supervisor descendants in a job that closes with the monitor process."""
import ctypes
from ctypes import wintypes as w
import os


def attach(process):
    if os.name != 'nt':
        return None
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),
                  ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(name,ctypes.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                  ('peak_process_memory',ctypes.c_size_t),('peak_job_memory',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateJobObjectW(None,None)
    info=Extended(); info.basic.flags=0x2000
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,w.HANDLE(int(process._handle))):
        if handle: kernel.CloseHandle(handle)
        process.terminate(); process.wait(timeout=3)
        raise RuntimeError('无法建立后台子进程清理边界，任务未启动。')
    return handle  # Intentionally owned until monitor exits; OS then kills descendants.


def close(handle):
    if handle and os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CloseHandle.argtypes=[w.HANDLE]
        kernel.CloseHandle(handle)
