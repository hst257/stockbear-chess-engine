"""Lightweight Windows CPU deltas between serial benchmark positions."""
import ctypes as c
from ctypes import wintypes as w

k = c.WinDLL('kernel32', use_last_error=True)
k.GetSystemTimes.argtypes = [c.POINTER(w.FILETIME)] * 3
k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
k.OpenProcess.restype = w.HANDLE
k.CloseHandle.argtypes = [w.HANDLE]
k.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4


def integer(value):
    return (value.dwHighDateTime << 32) + value.dwLowDateTime


class Meter:
    def __init__(self, pids):
        self.handles = [k.OpenProcess(0x1000, False, pid) for pid in pids]
        if not all(self.handles):
            self.close()
            raise c.WinError(c.get_last_error())
        self.previous = self.snapshot()

    def snapshot(self):
        values = [w.FILETIME() for _ in range(3)]
        if not k.GetSystemTimes(*[c.byref(v) for v in values]):
            raise c.WinError(c.get_last_error())
        own = 0
        for handle in self.handles:
            times = [w.FILETIME() for _ in range(4)]
            if not k.GetProcessTimes(handle, *[c.byref(v) for v in times]):
                raise c.WinError(c.get_last_error())
            own += integer(times[2]) + integer(times[3])
        return integer(values[0]), integer(values[1]) + integer(values[2]), own

    def read(self):
        current = self.snapshot()
        idle, total, own = [a-b for a,b in zip(current, self.previous)]
        self.previous = current
        busy = 100 * (1-idle/total)
        return {'system_cpu_percent': busy, 'benchmark_process_cpu_percent': 100*own/total,
                'other_cpu_percent_estimate': max(0, busy-100*own/total),
                'method': 'System FILETIME minus own Python and child-engine process CPU deltas, percent of total logical capacity; not per-core contention or thermal telemetry'}

    def close(self):
        for handle in self.handles:
            if handle: k.CloseHandle(handle)
        self.handles = []
