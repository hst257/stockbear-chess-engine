"""The trained export, native inference, incremental state and evaluator selection."""
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

import chess
import chess.engine
import pygame
import pytest

from app.engine_client import EngineSettings
from app.engine_client import EngineClient
from tests.test_engine_client import wait_result
from app.ui import engine_panels
from tests.test_engine import protocol
from tests.test_engine_ui import app, click, human_e4
from tools.embed_nnue import DEFAULT_MODEL, read_model

GOLDENS = json.loads(DEFAULT_MODEL.with_suffix(".golden.json").read_text())


def features(board, perspective):
    result = []
    for square, piece in board.piece_map().items():
        relative = 0 if piece.color == perspective else 1
        oriented = square if perspective else square ^ 56
        result.append((relative * 6 + piece.piece_type - 1) * 64 + oriented)
    for relative, color in enumerate((perspective, not perspective)):
        if board.has_kingside_castling_rights(color):
            result.append(768 + relative * 2)
        if board.has_queenside_castling_rights(color):
            result.append(769 + relative * 2)
    if board.has_legal_en_passant():
        result.append(772 + chess.square_file(board.ep_square))
    return sorted(result)


def native_eval(engine_path, fen):
    return json.loads(subprocess.check_output([str(engine_path), "--eval", "--nnue", fen], text=True))


@pytest.mark.parametrize("row", GOLDENS, ids=lambda row: row["fen"])
def test_native_matches_trained_golden(engine_path, row):
    value = native_eval(engine_path, row["fen"])
    assert abs(value["side_to_move_cp"] - row["side_to_move_cp"]) < .01
    assert (value["width"], value["hidden"]) == (32, 16)
    assert value["sha256"] == hashlib.sha256(DEFAULT_MODEL.read_bytes()).hexdigest()


@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
    "7k/8/8/3pP3/8/8/8/K7 w - d6 0 1",
    "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1",  # EP is pinned.
    "4r2k/8/8/2PpP3/8/8/8/4K3 w - d6 0 1",  # Other pawn can take.
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "7k/4P3/8/8/8/8/8/K7 w - - 0 1"])
def test_feature_contract_and_independent_forward_pass(engine_path, fen):
    _, weights, _ = read_model(DEFAULT_MODEL)
    board = chess.Board(fen)
    for board in (board, board.mirror()):
        value = native_eval(engine_path, board.fen(en_passant="fen"))
        active = [features(board, c) for c in (chess.WHITE, chess.BLACK)]
        assert value["features"] == active
        accumulators = [[weights["bias"][j] + sum(weights["transform.weight"][f * 32 + j] for f in group)
                         for j in range(32)] for group in active]
        order = (0, 1) if board.turn else (1, 0)
        inputs = [min(1, max(0, v)) for p in order for v in accumulators[p]]
        hidden = [min(1, max(0, weights["fc1.bias"][h] +
                            sum(weights["fc1.weight"][h * 64 + j] * inputs[j] for j in range(64))))
                  for h in range(16)]
        expected = 400 * (weights["fc2.bias"][0] + sum(weights["fc2.weight"][h] * hidden[h] for h in range(16)))
        assert abs(value["side_to_move_cp"] - expected) < .01


@pytest.mark.parametrize("damage", ("magic", "truncated", "payload", "feature", "shape", "nan"))
def test_model_validation_rejects_bad_exports(tmp_path, damage):
    data = bytearray(DEFAULT_MODEL.read_bytes())
    size, = struct.unpack_from("<I", data, 8)
    header = json.loads(data[12:12 + size])
    payload = bytearray(data[12 + size:])
    if damage == "magic":
        data[0] = 0
    elif damage == "truncated":
        data = data[:10]
    elif damage == "payload":
        data[-1] ^= 1
    else:
        if damage == "feature":
            header["feature_version"] = "wrong"
        elif damage == "shape":
            header["tensors"][0]["shape"] = [999]
        elif damage == "nan":
            struct.pack_into("<f", payload, 0, math.nan)
            header["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        encoded = json.dumps(header).encode()
        data = data[:8] + struct.pack("<I", len(encoded)) + encoded + payload
    path = tmp_path / "bad.sbnnue"
    path.write_bytes(data)
    with pytest.raises(ValueError):
        read_model(path)


@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
    "7k/4P3/8/8/8/8/8/K7 w - - 0 1"])
def test_incremental_search_agrees_with_rebuild(engine, fen):
    engine.configure({"Evaluator": "nnue", "Quiescence": True, "PVS": True})
    scores = []
    for enabled in (False, True):
        engine.configure({"NNUEIncremental": enabled})
        board = chess.Board(fen)
        result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 3 and result.move in board.legal_moves
        score = result.info["score"].white()
        scores.append(score.score(mate_score=30000))
        for move in result.info["pv"]:
            assert move in board.legal_moves
            board.push(move)
    assert abs(scores[0] - scores[1]) <= 1


def test_mode_switch_keeps_classical_scores_and_caches_separate(engine):
    assert engine.options["Evaluator"].default == "classical"
    assert engine.options["Evaluator"].var == ["classical", "nnue"]
    engine.configure({"TranspositionTable": True, "UseAdvancedEvaluation": True, "UsePST": True})
    results = []
    for mode in ("classical", "nnue", "classical", "nnue"):
        engine.configure({"Evaluator": mode})
        result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        results.append((result.info["score"], result.move, result.info["nodes"]))
    assert results[0] == results[2] and results[1] == results[3]
    assert results[0][0] != results[1][0]


def test_nnue_ignores_classical_category_settings(engine):
    engine.configure({"Evaluator": "nnue"})
    before = engine.play(chess.Board(), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    engine.configure({"UsePST": True, "UseAdvancedEvaluation": True, "EvalMobility": False,
                      "WeightPawnsEG": 0, "UseMopUp": False})
    after = engine.play(chess.Board(), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert before.info["score"] == after.info["score"] and before.move == after.move


@pytest.mark.parametrize("fen", ["7k/8/8/8/8/8/8/K7 w - - 0 1",
    "7k/8/8/8/8/8/8/KN6 w - - 0 1", chess.STARTING_FEN.replace("0 1", "100 1"),
    "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"])
def test_nnue_preserves_terminal_precedence(engine, fen):
    board = chess.Board(fen)
    engine.configure({"Evaluator": "nnue"})
    result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert not result.move
    if board.is_checkmate():
        assert result.info["score"].pov(board.turn).mate() == 0
    else:
        assert result.info["score"].white().score() == 0


def test_evaluator_option_validation(protocol):
    protocol.send("setoption name Evaluator value other")
    assert "Evaluator must" in protocol.until("info string error")[-1]
    protocol.send("setoption name NNUEIncremental value 1")
    assert "true or false" in protocol.until("info string error")[-1]


def test_gui_selector_and_pending_request_snapshot(app):
    human_e4(app)
    original = app.engine.calls[-1][2]
    app.action("setup")
    app.draw()
    click(app, app.modal_targets["toggle_evaluator"].center)
    assert app.draft_settings.evaluator == "nnue" and original.evaluator == "classical"
    click(app, app.modal_targets["apply"].center)
    assert app.settings.evaluator == "nnue" and not app.engine.busy
    app.update_engine()
    assert app.engine.calls[-1][2].evaluator == "nnue"
    assert app.game.board.peek() == chess.Move.from_uci("e2e4")


def test_gui_search_lab_switch_and_inactive_pst(app):
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["toggle_evaluator"].center)
    assert app.settings.evaluator == "nnue"
    assert engine_panels.adjust(app.settings, "toggle_evaluator").evaluator == "classical"
    previous = app.settings.use_pst
    click(app, app.modal_targets["toggle_pst"].center)
    assert app.settings.use_pst == previous
    app.engine.busy = True
    click(app, app.modal_targets["toggle_evaluator"].center)
    assert app.settings.evaluator == "nnue"
    app.engine.busy = False


def test_settings_reject_unknown_evaluator():
    with pytest.raises(ValueError):
        EngineSettings(evaluator="unknown")


def test_real_worker_preserves_nnue_settings_and_result(engine_path):
    client = EngineClient(engine_path)
    try:
        board = chess.Board()
        client.start(board, 7, EngineSettings(enabled=True, evaluator="nnue", thinking_time_ms=100))
        message = wait_result(client)
        assert not message.error and message.revision == 7
        assert message.stats[0].evaluator == "nnue"
        assert message.stats[0].move in board.legal_moves and message.stats[0].depth > 0
        assert board.fen() == chess.STARTING_FEN
    finally:
        client.close()
