"""Dependency-free validation before a GUI worker selects experimental v3."""
from array import array
import hashlib
import math
from pathlib import Path
import struct
import sys

DEFAULT_V3_MODEL = Path(__file__).resolve().parents[1] / "engine/networks/v3/stockbear-v3-selected.sbnnue"


def validate_model(path: Path) -> Path:
    raw = path.read_bytes()
    if len(raw) < 72 or len(raw) > 5248972:
        raise ValueError("Missing or invalid-size NNUE v3 model")
    magic, version, contract, features, width, hidden, precision, scale, tensors, checksum = struct.unpack_from("<8s8I32s", raw)
    if (magic != b"SBNNUE3\0" or version != 3 or (contract, features) not in ((1, 40972), (2, 10252))
            or (width, hidden, precision, scale, tensors) != (32, 16, 4, 400, 6)):
        raise ValueError("Incompatible NNUE v3 model contract")
    payload = raw[72:]
    if len(payload) != ((features + 1) * 32 + 1089) * 4 or hashlib.sha256(payload).digest() != checksum:
        raise ValueError("NNUE v3 weight size/checksum mismatch")
    weights = array("f")
    weights.frombytes(payload)
    if sys.byteorder != "little":
        weights.byteswap()
    if any(not math.isfinite(v) or abs(v) > 1e6 for v in weights) or any(weights[32 + features * 32:32 + (features + 1) * 32]):
        raise ValueError("NNUE v3 weights must be finite with zero padding")
    return path.resolve()
