"""Fixed, versioned little-endian format; no v2 reader or weights are changed."""
from __future__ import annotations

import hashlib
from pathlib import Path
import struct

import numpy as np

from .features import FEATURES, PADDING

HEADER = struct.Struct("<8s8I32s")
MAGIC = b"SBNNUE3\0"
FIELDS = (3, 1, FEATURES, 32, 16, 4, 400, 6)
SHAPES = {"bias": (32,), "transform.weight": (FEATURES + 1, 32),
          "fc1.weight": (16, 64), "fc1.bias": (16,),
          "fc2.weight": (1, 16), "fc2.bias": (1,)}
PAYLOAD_BYTES = sum(int(np.prod(s)) * 4 for s in SHAPES.values())


def write_model(path: Path, model) -> dict:
    if path.exists():
        raise FileExistsError(path)
    arrays = model.state_dict()
    payload = b"".join(np.asarray(arrays[n].detach().cpu().numpy(), dtype="<f4").tobytes()
                       for n in SHAPES)
    checksum = hashlib.sha256(payload).digest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(HEADER.pack(MAGIC, *FIELDS, checksum) + payload)
    read_model(path)
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "payload_sha256": checksum.hex(), "bytes": path.stat().st_size,
            "parameters": PAYLOAD_BYTES // 4, "format_version": 3, "feature_contract": 1}


def read_model(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    if len(raw) != HEADER.size + PAYLOAD_BYTES:
        raise ValueError("Invalid v3 file size")
    magic, *values = HEADER.unpack_from(raw)
    if magic != MAGIC or tuple(values[:-1]) != FIELDS:
        raise ValueError("Incompatible v3 model contract")
    payload = raw[HEADER.size:]
    if hashlib.sha256(payload).digest() != values[-1]:
        raise ValueError("V3 checksum mismatch")
    arrays, offset = {}, 0
    for name, shape in SHAPES.items():
        count = int(np.prod(shape))
        arrays[name] = np.frombuffer(payload, dtype="<f4", count=count, offset=offset).reshape(shape)
        offset += count * 4
        if not np.isfinite(arrays[name]).all():
            raise ValueError("Nonfinite v3 weights")
    if np.any(arrays["transform.weight"][PADDING] != 0):
        raise ValueError("V3 padding row must be zero")
    return arrays
