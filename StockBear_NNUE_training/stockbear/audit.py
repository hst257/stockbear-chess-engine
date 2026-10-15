from __future__ import annotations

import importlib.metadata
import os
import platform
import shutil
import subprocess
from pathlib import Path

import chess.engine
import psutil
import torch

from .common import file_hash, save_json
from .teacher import find_teacher


def audit(root: Path, cfg: dict) -> dict:
    exe = find_teacher(root)
    with chess.engine.SimpleEngine.popen_uci(str(exe), timeout=30) as engine:
        teacher = {"path": str(exe), "sha256": file_hash(exe), "identity": engine.id,
                   "options": {key: {"default": option.default, "min": option.min, "max": option.max}
                               for key, option in engine.options.items()}}
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(root)
    cpu_brand = platform.processor()
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu_brand = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    gpu = {"cuda_available": torch.cuda.is_available(), "torch_cuda": torch.version.cuda}
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        # A real operation checks driver/runtime compatibility, beyond enumerating a GPU.
        matrix = torch.randn(64, 64, device="cuda")
        (matrix @ matrix).sum().item()
        gpu.update(name=props.name, memory_bytes=props.total_memory, capability=list(torch.cuda.get_device_capability()))
    raw = [{"path": str(p), "bytes": p.stat().st_size, "sha256": file_hash(p)} for p in sorted((root / "data/raw").glob("*.zst"))]
    try:
        nvidia = subprocess.check_output(["nvidia-smi", "--query-gpu=name,driver_version,memory.total", "--format=csv,noheader"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        nvidia = None
    report = {"root": str(root), "platform": platform.platform(), "python": platform.python_version(),
              "python_executable": os.sys.executable, "cpu": cpu_brand, "physical_cores": psutil.cpu_count(logical=False),
              "logical_cores": os.cpu_count(), "ram_bytes": memory.total, "available_ram_bytes": memory.available,
              "disk_free_bytes": disk.free, "gpu": gpu, "nvidia_smi": nvidia, "teacher": teacher, "raw_files": raw,
              "packages": {name: importlib.metadata.version(name) for name in ("torch", "chess", "zstandard", "numpy", "psutil", "pytest")}}
    if disk.free < 5 * (1 << 30):
        raise RuntimeError("Less than 5 GiB free; free disk space before sampling")
    save_json(root / cfg["run"] / "audit.json", report)
    return report
