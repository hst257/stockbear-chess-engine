"""Versioned v3 loading, isolated evaluator state, UI and worker contracts."""
import json
from pathlib import Path
import shutil

import chess
import chess.engine
import pytest

from app.engine_client import EngineClient, EngineSettings
from app.nnue_v3_model import DEFAULT_V3_MODEL, validate_model
from app.ui.engine_panels import adjust
from tests.test_engine import protocol
from tests.test_engine_client import wait_result


def test_release_selector_has_two_modes_and_default_is_classical():
    value = EngineSettings()
    assert value.evaluator == "classical"
    for expected in ("nnue", "classical", "nnue", "classical"):
        value = adjust(value, "toggle_evaluator")
        assert value.evaluator == expected


def test_gui_model_validation_rejects_corruption(tmp_path):
    assert validate_model(DEFAULT_V3_MODEL) == DEFAULT_V3_MODEL.resolve()
    damaged = bytearray(DEFAULT_V3_MODEL.read_bytes())
    damaged[-1] ^= 1
    path = tmp_path / "bad.sbnnue"
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="checksum"):
        validate_model(path)


def test_model_paths_with_spaces_and_failed_reload_preserve_selection(protocol, tmp_path):
    path = tmp_path / "model with spaces.sbnnue"
    shutil.copyfile(DEFAULT_V3_MODEL, path)
    protocol.send(f"setoption name NNUEV3File value {path}")
    protocol.send("setoption name Evaluator value nnue_v3")
    protocol.send("eval")
    first = json.loads(protocol.until("info string eval ")[-1].removeprefix("info string eval "))
    assert first["evaluator"] == "nnue_v3"
    protocol.send(f"setoption name NNUEV3File value {tmp_path / 'missing.sbnnue'}")
    assert "v3 model" in protocol.until("info string error")[-1]
    protocol.send("eval")
    second = json.loads(protocol.until("info string eval ")[-1].removeprefix("info string eval "))
    assert second == first


def test_switching_and_fresh_search_keep_each_evaluator_deterministic(engine):
    engine.configure({"NNUEV3File": str(DEFAULT_V3_MODEL), "TranspositionTable": True})
    seen = {}
    for evaluator in ("classical", "nnue", "nnue_v3", "nnue", "classical", "nnue_v3"):
        engine.configure({"Evaluator": evaluator})
        info = engine.analyse(chess.Board(), chess.engine.Limit(nodes=20000), game=object())
        value = (info["score"], info["nodes"], info["depth"], info["pv"])
        if evaluator in seen:
            assert seen[evaluator] == value
        seen[evaluator] = value


@pytest.mark.parametrize("fen", ["7k/8/8/8/8/8/8/K7 w - - 0 1",
    "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "7k/8/8/8/8/8/8/KR6 w - - 100 1"])
def test_v3_terminal_and_draw_precedence(engine, fen):
    engine.configure({"NNUEV3File": str(DEFAULT_V3_MODEL), "Evaluator": "nnue_v3"})
    board = chess.Board(fen)
    result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert not result.move
    if board.is_checkmate():
        assert result.info["score"].pov(board.turn).mate() == 0
    else:
        assert result.info["score"].white().score() == 0


def test_real_gui_worker_uses_v3_and_preserves_board(engine_path):
    client = EngineClient(engine_path)
    board = chess.Board()
    try:
        client.start(board, 19, EngineSettings(enabled=True, evaluator="nnue_v3", thinking_time_ms=100))
        result = wait_result(client)
        assert not result.error and result.revision == 19
        assert result.stats[0].evaluator == "nnue_v3"
        assert result.stats[0].move in board.legal_moves
        assert board.fen() == chess.STARTING_FEN
    finally:
        client.close()


def test_missing_v3_model_becomes_worker_error_without_playing(engine_path, tmp_path):
    client = EngineClient(engine_path)
    try:
        client.start(chess.Board(), 20, EngineSettings(enabled=True, evaluator="nnue_v3",
            v3_model=str(tmp_path / "missing.sbnnue"), thinking_time_ms=100))
        result = wait_result(client)
        assert result.error and not result.stats
    finally:
        client.close()
