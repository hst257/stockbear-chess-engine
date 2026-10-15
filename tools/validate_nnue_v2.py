"""Compare candidate native outputs with frozen float32 and trained goldens."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import subprocess

import chess
from tools.benchmark_nnue_v2 import POSITIONS
from tools.audit_engine import metadata


def corpus() -> list[tuple[str, str]]:
    root = Path("StockBear_NNUE_training")
    cfg = json.loads((root / "configs/v2/plan.json").read_text())
    with sqlite3.connect((root / cfg["pool"]).resolve().as_uri() + "?mode=ro", uri=True) as db:
        heldout = list(db.execute("SELECT fen,phase FROM positions WHERE split='test' AND ordinal<=200000 ORDER BY ordinal"))
    assert len(heldout) == 20152
    rows = [(fen, "heldout_" + phase) for fen, phase in heldout]
    rng = random.Random(20261015)
    board = chess.Board()
    for i in range(2000):
        if board.is_game_over() or i % 160 == 0:
            board = chess.Board()
        board.push(rng.choice(list(board.legal_moves)))
        rows.append((board.fen(en_passant="fen"), "random"))
    rows.extend((fen, category) for category, fen in POSITIONS.items())
    rows.extend((fen, "extreme") for fen in (
        "7k/8/8/8/8/8/PPPPPPPP/KQQQQQQQ w - - 0 1",
        "kqqqqqqq/pppppppp/8/8/8/8/8/7K b - - 0 1",
        "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1"))
    return rows


def errors(reference: list[float], candidate: list[float]) -> dict[str, int | float]:
    diff = [abs(a - b) for a, b in zip(reference, candidate)]
    return {"n": len(diff), "mae_cp": sum(diff) / len(diff), "max_cp": max(diff),
            "rmse_cp": math.sqrt(sum(d*d for d in diff) / len(diff)),
            "sign_disagreements": sum((a > 0) != (b > 0) for a, b in zip(reference, candidate))}


def batch(path: Path | str, rows: list[tuple[str, str]], kernel: str | None = None) -> list[float]:
    command = [str(Path(path).resolve()), "--batch"] + ([kernel] if kernel else [])
    out = subprocess.check_output(command, input="\n".join(fen for fen, _ in rows) + "\n", text=True, timeout=120)
    values = [float(v) for v in out.splitlines()]
    assert len(values) == len(rows) and all(math.isfinite(v) for v in values)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh report")
    configs = json.loads(args.config.read_text())
    rows = corpus()
    report = {"method": "20152 original grouped test positions, 2000 seeded random legal positions, ten category fixtures and three extremes; no training or selection on teacher targets", "corpus_sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(), "configurations": {}}
    for label, config in configs.items():
        if not config.get("micro") or label.startswith("original-") or label == "v1":
            continue
        binary = Path(config["micro"])
        build = json.loads(binary.with_suffix(".build.json").read_text())
        model = Path(build["nnue"]["model"])
        model_name = "small" if build["nnue"]["width"] == 64 else "compact"
        kernel = config.get("kernel")
        golden = json.loads(model.with_suffix(".golden.json").read_text())
        golden_values = batch(binary, [(r["fen"], "golden") for r in golden], kernel)
        reference = batch(f"artifacts/nnue-v2/baseline-{model_name}/micro.exe", rows)
        values = batch(binary, rows, kernel)
        record = {"metadata": metadata(binary), "build": build, "kernel": kernel,
                  "golden": errors([r["side_to_move_cp"] for r in golden], golden_values),
                  "all": errors(reference, values), "by_category": {}}
        for category in sorted({c for _, c in rows}):
            selected = [i for i, (_, c) in enumerate(rows) if c == category]
            record["by_category"][category] = errors([reference[i] for i in selected], [values[i] for i in selected])
        if kernel not in ("quant", "quant-simd"):
            assert record["golden"]["max_cp"] < .01 and record["all"]["max_cp"] < .01
        else:
            assert record["all"]["max_cp"] < 5 and record["all"]["mae_cp"] < 1
        command = [str(binary.resolve()), "--verify"] + ([kernel] if kernel else [])
        record["incremental"] = json.loads(subprocess.check_output(command, text=True, timeout=120))
        report["configurations"][label] = record
        print(label, record["all"], record["incremental"], flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
