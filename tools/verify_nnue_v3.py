"""Cross-language v3 feature, forward, malformed-model and transition gates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StockBear_NNUE_training"))

import chess
import numpy as np
import torch

from stockbear.v3.features import active_features, encode, feature_count
from stockbear.v3.export import HEADER, read_model, model_buckets
from stockbear.v3.model import KingRelativeNNUE


def corpus(size: int) -> list[chess.Board]:
    fixtures = [chess.STARTING_FEN,
        "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
        "7k/4P3/8/8/8/8/8/K7 w - - 0 1",
        "4r2k/8/8/2PpP3/8/8/8/4K3 w - d6 0 1",
        "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "8/8/8/3k4/8/4K3/3P4/8 w - - 0 1"]
    boards = [chess.Board(fen) for fen in fixtures]
    for board in list(boards):
        for move in list(board.legal_moves):
            child = board.copy(stack=False)
            child.push(move)
            boards.append(child)
    boards += [b.mirror() for b in boards]
    rng = random.Random(20261016)
    board = chess.Board()
    while len(boards) < size:
        if board.is_game_over() or board.ply() > 180:
            board = chess.Board()
        board.push(rng.choice(list(board.legal_moves)))
        boards.append(board.copy(stack=False))
    return boards[:size]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--probe", type=Path, default=Path("artifacts/nnue-v3/probe.exe"))
    parser.add_argument("--positions", type=int, default=4096)
    parser.add_argument("--heldout", action="store_true", help="Use the original grouped test FENs, only to check native parity.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    arrays = read_model(args.model)
    buckets = model_buckets(args.model)
    model = KingRelativeNNUE(buckets)
    model.load_state_dict({n: torch.from_numpy(v.copy()) for n, v in arrays.items()})
    model.eval()
    if args.heldout:
        pool = ROOT / "StockBear_NNUE_training/data/v2/pool.sqlite"
        with sqlite3.connect(f"file:{pool.as_posix()}?mode=ro", uri=True) as db:
            boards = [chess.Board(fen) for fen, in db.execute(
                "SELECT fen FROM positions WHERE split='test' AND ordinal<=200000 ORDER BY ordinal LIMIT ?", (args.positions,))]
    else:
        boards = corpus(args.positions)
    packed = np.stack([encode(b, buckets) for b in boards]).astype(np.int64)
    with torch.inference_mode():
        expected = model(torch.from_numpy(packed)).numpy() * 400
    training_device_error = None
    if args.heldout:
        selection = json.loads((ROOT / "StockBear_NNUE_training/reports/v3/selection.json").read_text())
        stored = np.load(ROOT / "StockBear_NNUE_training/runs/v3" / selection["run"] / "test_predictions.npy")[:len(expected)]
        training_device_error = float(np.max(np.abs(stored - expected)))
        assert training_device_error < .02
    proc = subprocess.run([str(args.probe.resolve()), str(args.model.resolve())],
        input="\n".join(b.fen(en_passant="fen") for b in boards) + "\n",
        capture_output=True, text=True, check=True, timeout=120)
    rows = [json.loads(line) for line in proc.stdout.splitlines()]
    assert len(rows) == len(boards)
    errors = []
    for board, row, value in zip(boards, rows, expected):
        assert row["features"] == [active_features(board, c, buckets) for c in (chess.WHITE, chess.BLACK)]
        assert np.array_equal(encode(board, buckets), encode(board.mirror(), buckets))
        errors.append(abs(row["cp"] - float(value)))
    assert max(errors) <= .02, max(errors)
    transitions = json.loads(subprocess.check_output([str(args.probe.resolve()), str(args.model.resolve()), "--verify"], text=True, timeout=120))
    head_native = json.loads(subprocess.check_output([str(args.probe.resolve()), str(args.model.resolve()), "--head"], text=True, timeout=20))
    patterns = [-1e6, -1, 0, 1e-7, .5, 1, 1.0000001, 1e6]
    head_expected = []
    with torch.inference_mode():
        for n in range(8):
            frame = torch.tensor([[patterns[(n+p+j) % 8] for j in range(32)] for p in range(2)])
            for turn in range(2):
                activated = frame[[turn, turn ^ 1]].clamp(0, 1).reshape(64)
                head_expected.append(float(model.fc2(model.fc1(activated).clamp(0, 1)).item() * 400))
    head_error = max(abs(a-b) for a,b in zip(head_native, head_expected))
    assert head_error < .02, head_error
    malformed = {}
    raw = args.model.read_bytes()
    scratch = ROOT / "artifacts/nnue-v3/malformed" / args.output.stem
    scratch.mkdir(parents=True, exist_ok=True)
    for kind in ("magic", "size", "version", "contract", "checksum", "nan", "overflow", "padding"):
        changed = bytearray(raw)
        if kind == "magic": changed[0] ^= 1
        elif kind == "size": changed = changed[:-1]
        elif kind in ("version", "contract"): struct.pack_into("<I", changed, 8 if kind == "version" else 12, 999)
        elif kind == "checksum": changed[-1] ^= 1
        else:
            offset = HEADER.size if kind in ("nan", "overflow") else HEADER.size + (32 + feature_count(buckets) * 32) * 4
            struct.pack_into("<f", changed, offset, float("nan") if kind == "nan" else 1e38 if kind == "overflow" else 1.0)
            changed[40:72] = hashlib.sha256(changed[72:]).digest()
        path = scratch / (kind + ".sbnnue")
        path.write_bytes(changed)
        try:
            read_model(path)
        except ValueError:
            pass
        else:
            raise AssertionError("Python accepted " + kind)
        result = subprocess.run([str(args.probe.resolve()), str(path.resolve())], capture_output=True, text=True, timeout=20)
        assert result.returncode != 0, kind
        malformed[kind] = result.stderr.strip()
    result = {"model_sha256": hashlib.sha256(raw).hexdigest(), "positions": len(rows), "grouped_heldout_fens": args.heldout,
        "exact_feature_indices": True, "normalized_color_symmetry": True,
        "max_abs_cp_error": max(errors), "mean_abs_cp_error": float(np.mean(errors)),
        "transitions": transitions, "malformed_rejected": malformed,
        "activation_boundary_and_extreme_head_cases": 16, "max_extreme_head_cp_error": head_error,
        "max_training_gpu_vs_cpu_cp_error": training_device_error,
        "tolerance": {"forward_cp": .02, "incremental_cp": .02, "incremental_lane": 1e-4}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
