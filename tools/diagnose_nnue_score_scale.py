"""Describe static score scale against independent searched scores, without tuning."""
from __future__ import annotations

import json
import math
import statistics
import subprocess

import chess

from tools.nnue_diagnosis import RELEASE, ROOT, metadata, prepare_suite, save


def comparison(rows: list[dict], evaluator: str) -> dict:
    if not rows:
        return {"positions": 0}
    x = [r["reference_root_cp"] for r in rows]
    y = [r[evaluator]["side_to_move_cp"] for r in rows]
    mx, my = statistics.mean(x), statistics.mean(y)
    xx = sum((v - mx) ** 2 for v in x)
    yy = sum((v - my) ** 2 for v in y)
    xy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return {"positions": len(rows), "mae_cp": statistics.mean(abs(a - b) for a, b in zip(x, y)),
            "mean_reference_cp": mx, "mean_static_cp": my,
            "median_abs_reference_cp": statistics.median(abs(v) for v in x),
            "median_abs_static_cp": statistics.median(abs(v) for v in y),
            "ols_static_on_searched_slope": xy / xx if xx else None,
            "correlation": xy / math.sqrt(xx * yy) if xx and yy else None,
            "decisive_sign_disagreements": sum((a > 0) != (b > 0) for a, b in zip(x, y) if abs(a) >= 100),
            "decisive_positions": sum(abs(a) >= 100 for a in x)}


def main() -> None:
    path = ROOT / "static-score-diagnosis.json"
    if path.exists():
        raise ValueError("Frozen score diagnosis exists")
    suite = prepare_suite()
    reference = {r["position"]: r for r in json.loads((ROOT / "stockfish-quality.json").read_text(encoding="utf-8"))["records"]}
    plan = json.loads((ROOT / "match-plan.json").read_text(encoding="utf-8"))
    records = []
    for row in suite["positions"]:
        board = chess.Board(row["fen"])
        result = {"position": row["id"], "category": row["category"], "fen": row["fen"],
                  "reference_root_cp": reference[row["id"]]["root"]["score_root"]["cp"],
                  "reference_root_mate": reference[row["id"]]["root"]["score_root"]["mate"]}
        for evaluator in ("nnue", "classical"):
            flags = ["--nnue", "--kernel", "scalar"] if evaluator == "nnue" else []
            raw = json.loads(subprocess.check_output([str(RELEASE.resolve()), "--eval", *flags, row["fen"]], text=True, timeout=10))
            if evaluator == "nnue":
                assert raw["sha256"] == plan["model_sha256"] and raw["width"] == 32 and raw["hidden"] == 16
            result[evaluator] = {"white_cp": raw["total"], "side_to_move_cp": raw["total"] * (1 if board.turn else -1), "raw": raw}
        records.append(result)
    finite = [r for r in records if r["reference_root_cp"] is not None]
    balanced = [r for r in finite if abs(r["reference_root_cp"]) <= 500]
    data = {"metadata": metadata(RELEASE),
            "method": "Static White scores converted to root side-to-move and compared with SF19 root searches at 300k nodes. These are different horizons: errors mix static-evaluation limitations and tactics. Twenty-four selected positions cannot establish global calibration or justify changing scale. Mate references remain separate. Training uses 0.9*sigmoid(clamp(teacher_cp,-2000,2000)/400)+0.1*game_result, sigmoid-space MSE; it does not directly minimize CP error.",
            "records": records, "finite_reference_summary": {e: comparison(finite, e) for e in ("nnue", "classical")},
            "balanced_reference_summary": {e: comparison(balanced, e) for e in ("nnue", "classical")}}
    save(path, data)


if __name__ == "__main__":
    main()
