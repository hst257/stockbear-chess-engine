"""Describe final held-out strata without changing model selection or targets."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StockBear_NNUE_training"))

import chess
import numpy as np

from stockbear.v2.learn import statistics


def main() -> None:
    train = ROOT / "StockBear_NNUE_training"
    selection = json.loads((train / "reports/v3/selection.json").read_text())
    predictions = {"v2": np.load(train / "runs/v2/final_compact_1250000_base/test_predictions.npy"),
                   "v3": np.load(train / "runs/v3" / selection["run"] / "test_predictions.npy")}
    y = np.load(train / "data/v2/prepared/1250000/test_y.npy")
    previous = json.loads((train / "reports/v3/heldout.json").read_text())
    for name, values in predictions.items():
        assert abs(statistics(values, y)["blended_mse"] - previous[name]["blended_mse"]) < 1e-9
    pool = train / "data/v2/pool.sqlite"
    with sqlite3.connect(f"file:{pool.as_posix()}?mode=ro", uri=True) as db:
        rows = list(db.execute("SELECT fen,flags FROM positions WHERE split='test' AND ordinal<=200000 ORDER BY ordinal"))
    assert len(rows) == len(y)
    masks = {"pawn_endgame": [], "rook_endgame": [], "king_pressure_heuristic": [],
             "promoted_configuration_heuristic": [], "passed_pawn_heuristic": []}
    for fen, flags in rows:
        board = chess.Board(fen)
        types = {p.piece_type for p in board.piece_map().values()}
        masks["pawn_endgame"].append(types <= {chess.PAWN, chess.KING})
        masks["rook_endgame"].append(types <= {chess.PAWN, chess.KING, chess.ROOK} and chess.ROOK in types)
        masks["king_pressure_heuristic"].append("king_pressure_heuristic" in flags)
        masks["promoted_configuration_heuristic"].append("unusual_piece_configuration" in flags)
        masks["passed_pawn_heuristic"].append("passed_pawn_heuristic" in flags)
    masks.update(material_imbalance=np.abs(y[:, 2]) >= 300, drawish_teacher=np.abs(y[:, 0]) <= 25)
    result = {"method": "Final selected-model held-out descriptions only; overlapping heuristic strata, no selection/tuning on these results.", "strata": {}}
    for name, values in masks.items():
        mask = np.asarray(values, dtype=bool)
        if mask.any():
            result["strata"][name] = {label: statistics(prediction[mask], y[mask]) for label, prediction in predictions.items()}
    (ROOT / "docs/nnue-v3/heldout-strata.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
