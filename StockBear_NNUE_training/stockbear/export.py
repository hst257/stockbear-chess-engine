from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import chess
import numpy as np

from .common import save_json
from .features import FEATURE_VERSION, FEATURES, active_features

MAGIC = b"SBNNUE1\x00"


def load_export(path: Path) -> tuple[dict, dict]:
    with path.open("rb") as stream:
        if stream.read(8) != MAGIC:
            raise ValueError("Invalid StockBear export magic")
        header_size = struct.unpack("<I", stream.read(4))[0]
        if header_size > 1 << 20:
            raise ValueError("Header too large")
        header = json.loads(stream.read(header_size))
        payload = stream.read()
    if header["feature_version"] != FEATURE_VERSION:
        raise ValueError("Unsupported features")
    if hashlib.sha256(payload).hexdigest() != header["payload_sha256"]:
        raise ValueError("Weight checksum mismatch")
    arrays = {}
    consumed = 0
    for item in header["tensors"]:
        count = int(np.prod(item["shape"]))
        size = count * 4
        if item["offset"] != consumed or item["dtype"] != "<f4" or consumed + size > len(payload):
            raise ValueError("Invalid tensor layout")
        arrays[item["name"]] = np.frombuffer(payload, dtype="<f4", count=count, offset=consumed).reshape(item["shape"])
        consumed += size
    if consumed != len(payload):
        raise ValueError("Trailing weight bytes")
    return header, arrays


def numpy_predict(board: chess.Board, weights: dict) -> float:
    accumulators = [weights["bias"] + weights["transform.weight"][active_features(board, color)].sum(axis=0)
                    for color in (board.turn, not board.turn)]
    activated = np.clip(np.concatenate(accumulators), 0, 1)
    hidden = np.clip(weights["fc1.weight"] @ activated + weights["fc1.bias"], 0, 1)
    return float((weights["fc2.weight"] @ hidden + weights["fc2.bias"]).item() * 400)


def export(root: Path, cfg: dict) -> dict:
    import torch
    from .model import NNUE

    run = root / cfg["run"]
    checkpoint = torch.load(run / "best.pt", map_location="cpu", weights_only=False)
    model = NNUE(**checkpoint["model_config"])
    model.load_state_dict(checkpoint["model"])
    model.eval()
    tensors = []
    payload = bytearray()
    for name, tensor in model.state_dict().items():
        array = np.ascontiguousarray(tensor.numpy(), dtype="<f4")
        tensors.append({"name": name, "shape": list(array.shape), "dtype": "<f4", "offset": len(payload)})
        payload.extend(array.tobytes())
    header = {"format": "StockBear float32 v1", "feature_version": FEATURE_VERSION,
              "features": FEATURES, "model": checkpoint["model_config"], "score_pov": "side_to_move",
              "output_cp_scale": 400, "activation": "clip(x,0,1)", "tensors": tensors,
              "payload_sha256": hashlib.sha256(payload).hexdigest(), "signature": checkpoint["signature"],
              "best_epoch": checkpoint["epoch"] + 1}
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    output = root / cfg["export"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(MAGIC + struct.pack("<I", len(encoded)) + encoded + payload)
    header_read, arrays = load_export(output)
    from .features import encode
    rows = [json.loads(line) for line in (run / "prepared/test_rows.jsonl").read_text(encoding="utf-8").splitlines()][:128]
    goldens, errors = [], []
    with torch.inference_mode():
        for row in rows:
            board = chess.Board(row["fen"])
            expected = float(model(torch.from_numpy(encode(board)[None])).item() * 400)
            actual = numpy_predict(board, arrays)
            errors.append(abs(expected - actual))
            goldens.append({"fen": row["fen"], "side_to_move_cp": expected})
    report = {"path": str(output), "bytes": output.stat().st_size, "parity_positions": len(rows),
              "max_abs_cp_error": max(errors), "mean_abs_cp_error": float(np.mean(errors)),
              "payload_sha256": header_read["payload_sha256"], "format": header_read["format"]}
    training_predictions = np.load(run / "test_predictions.npy")[:len(rows)]
    reference_predictions = np.array([item["side_to_move_cp"] for item in goldens])
    report["max_abs_cp_error_vs_training_device"] = float(np.max(np.abs(reference_predictions - training_predictions)))
    if report["max_abs_cp_error"] > 0.01:
        raise AssertionError(f"Export parity failed: {report}")
    if report["max_abs_cp_error_vs_training_device"] > 0.01:
        raise AssertionError(f"Training device parity failed: {report}")
    save_json(output.with_suffix(".golden.json"), goldens)
    save_json(run / "export_report.json", report)
    return report
