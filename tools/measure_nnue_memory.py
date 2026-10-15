"""Windows process memory sampled during real searches; separate from NPS trials."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import threading
import time

import chess
import chess.engine
from tools.audit_engine import metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Frozen report exists")
    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    report = {"method": "GetProcessMemoryInfo every 10ms during one 500ms search; working/private bytes include the entire engine and Hash=16MB; peak working set is OS lifetime peak", "configurations": {}}
    for label, config in json.loads(args.config.read_text()).items():
        binary = Path(config["engine"])
        with chess.engine.SimpleEngine.popen_uci(str(binary.resolve())) as engine:
            engine.configure(config.get("options", {}) | {"Hash": 16})
            handle = kernel.OpenProcess(0x410, False, engine.transport.get_pid())
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                samples, stop = [], threading.Event()
                def collect():
                    while not stop.is_set():
                        counters = Counters()
                        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), ctypes.sizeof(counters)):
                            raise ctypes.WinError(ctypes.get_last_error())
                        samples.append({"working_set_bytes": counters.WorkingSetSize, "private_bytes": counters.PrivateUsage,
                                        "peak_working_set_bytes": counters.PeakWorkingSetSize})
                        stop.wait(.01)
                worker = threading.Thread(target=collect)
                worker.start()
                try:
                    engine.play(chess.Board(), chess.engine.Limit(time=.5))
                finally:
                    stop.set(); worker.join()
                assert samples
                report["configurations"][label] = {"metadata": metadata(binary), "samples": len(samples),
                    "max": {key: max(s[key] for s in samples) for key in samples[0]}}
            finally:
                kernel.CloseHandle(handle)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
