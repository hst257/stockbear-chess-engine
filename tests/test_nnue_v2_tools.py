"""Contracts independent of the chosen embedded network or CPU ISA."""
import json
from pathlib import Path

import chess
import pytest

from tools.benchmark_nnue_v2 import POSITIONS, summary
from tools.validate_nnue_v2 import errors
from tools.embed_nnue import generate_header, read_model


def test_benchmark_categories_are_valid_orthodox_positions():
    assert len(POSITIONS) == 10
    assert all(chess.Board(fen).is_valid() for fen in POSITIONS.values())


def test_error_statistics_include_sign_and_phase_agnostic_units():
    assert errors([-1, 2], [1, 2]) == {"n": 2, "mae_cp": 1, "max_cp": 2,
                                      "rmse_cp": 2 ** .5, "sign_disagreements": 1}
    assert summary([{"nps": 1}, {"nps": 3}, {"nps": 2}], "nps")["median"] == 2


@pytest.mark.parametrize("name,width,hidden", [("compact", 32, 16), ("small", 64, 32)])
def test_bundled_v2_identity_and_transposed_layout(tmp_path, name, width, hidden):
    model = Path(f"engine/networks/v2/stockbear-v2-{name}.sbnnue")
    if not model.exists():
        # During development the original training export remains authoritative.
        model = Path(f"StockBear_NNUE_training/exports/v2/stockbear-v2-{name}.sbnnue")
    header, weights, checksum = read_model(model)
    assert header["model"]["width"] == width and header["model"]["hidden"] == hidden
    info = generate_header(model, tmp_path / "weights.hpp")
    assert info["sha256"] == checksum
    text = (tmp_path / "weights.hpp").read_text()
    transposed = text.split("float fc1_transposed[] = {", 1)[1].split("};", 1)[0]
    values = [float.fromhex(s.strip()[:-1]) for s in transposed.split(",") if s.strip()]
    assert values == [weights["fc1.weight"][h * 2 * width + j] for j in range(2 * width) for h in range(hidden)]
    assert len(json.loads(model.with_suffix(".golden.json").read_text())) == 128


@pytest.mark.parametrize("kernel", ["reference", "scalar", "auto"])
def test_kernel_switch_is_search_local_and_reproducible(engine, kernel):
    import chess.engine
    engine.configure({"Evaluator": "nnue", "NNUEKernel": kernel})
    a = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    engine.configure({"Evaluator": "classical"})
    engine.play(chess.Board(), chess.engine.Limit(depth=2))
    engine.configure({"Evaluator": "nnue", "NNUEKernel": kernel})
    b = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert (a.move, a.info["score"], a.info["nodes"]) == (b.move, b.info["score"], b.info["nodes"])
