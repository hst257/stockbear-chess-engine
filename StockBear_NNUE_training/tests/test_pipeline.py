import copy
import io
import json
import random
import sqlite3
from pathlib import Path

import chess
import chess.pgn
import numpy as np
import pytest
import torch
import zstandard

from stockbear.common import connect, digest, metadata
from stockbear.export import MAGIC, load_export, numpy_predict
from stockbear.features import FEATURES, MAX_ACTIVE, PADDING, active_features, encode, update_accumulator
from stockbear.model import NNUE
from stockbear.sample import SelectedGameBuilder, canonical_fen, choose_games, game_id, pgn_stream, positions_from_game, split_for
from stockbear.teacher import Worker


def test_feature_orientation_padding_and_stm():
    board = chess.Board()
    assert 0 * 64 + chess.A2 in active_features(board, chess.WHITE)
    assert 6 * 64 + chess.A7 in active_features(board, chess.WHITE)
    assert active_features(board, chess.WHITE) == active_features(board, chess.BLACK)
    x = encode(board)
    assert x.shape == (2, MAX_ACTIVE)
    assert (x[0] == PADDING).sum() == 1
    board.push_uci("e2e4")
    white_features = active_features(board, chess.WHITE)
    black_features = active_features(board, chess.BLACK)
    board.turn = not board.turn
    changed = encode(board)
    assert changed[0, :len(white_features)].tolist() == white_features
    assert changed[1, :len(black_features)].tolist() == black_features
    assert changed.min() >= 0 and changed.max() <= FEATURES


@pytest.mark.parametrize("fen,uci", [
    (chess.STARTING_FEN, "e2e4"),
    ("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "e1g1"),
    ("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6"),
    ("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "a7a8q"),
    ("4k3/8/8/8/8/8/r7/R3K3 w Q - 0 1", "a1a2"),
    ("4k3/8/8/8/8/8/8/4K3 w - - 0 1", "e1f1"),
])
def test_incremental_special_moves(fen, uci):
    before = chess.Board(fen)
    after = before.copy()
    after.push_uci(uci)
    weights = np.random.default_rng(1).normal(size=(FEATURES + 1, 128)).astype(np.float32)
    bias = np.ones(128, dtype=np.float32)
    for color in chess.COLORS:
        accumulator = bias + weights[active_features(before, color)].sum(axis=0)
        updated = update_accumulator(accumulator, before, after, color, weights)
        rebuilt = bias + weights[active_features(after, color)].sum(axis=0)
        np.testing.assert_allclose(updated, rebuilt, atol=4e-6, rtol=2e-5)


def test_random_incremental_sequence_and_undo():
    rng = random.Random(14)
    weights = np.random.default_rng(7).normal(size=(FEATURES + 1, 16)).astype(np.float64)
    board = chess.Board()
    acc = {c: weights[active_features(board, c)].sum(axis=0) for c in chess.COLORS}
    for _ in range(150):
        if board.is_game_over():
            break
        previous = board.copy()
        board.push(rng.choice(list(board.legal_moves)))
        for c in chess.COLORS:
            acc[c] = update_accumulator(acc[c], previous, board, c, weights)
            np.testing.assert_allclose(acc[c], weights[active_features(board, c)].sum(axis=0), atol=1e-12)
        if rng.random() < 0.2:
            after = board.copy()
            board.pop()
            for c in chess.COLORS:
                acc[c] = update_accumulator(acc[c], after, board, c, weights)
                np.testing.assert_allclose(acc[c], weights[active_features(board, c)].sum(axis=0), atol=1e-12)


def test_game_group_and_canonical_position():
    headers = {"Event": "Cup", "White": "A", "Black": "B", "Date": "2026.06.01", "Round": "1"}
    identity = game_id(headers)
    headers.update(Result="1-0", PlyCount="30")
    assert game_id(headers) == identity
    assert {split_for(identity, 42) for _ in range(10)} <= {"train", "validation", "test"}
    board = chess.Board()
    fen = canonical_fen(board)
    board.halfmove_clock, board.fullmove_number = 35, 60
    assert canonical_fen(board) == fen
    board.push_uci("e2e4")
    assert canonical_fen(board).split()[3] == "-"  # pseudo-legal EP is omitted


def test_multiframe_stream_selection_and_duplicate_group(tmp_path):
    games = []
    for i in range(30):
        games.append(f'[Event "Cup"]\n[Date "2026.06.01"]\n[Round "{i}"]\n[White "A"]\n[Black "B"]\n[Result "1/2-1/2"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 1/2-1/2\n\n')
    path = tmp_path / "sample.pgn.zst"
    compressor = zstandard.ZstdCompressor()
    path.write_bytes(compressor.compress("".join(games[:15]).encode()) + compressor.compress("".join(games[15:]).encode()))
    selected, report = choose_games(path, 10, 13)
    assert report == {"games_seen": 30, "selected_games": 10}
    assert selected == choose_games(path, 10, 13)[0]
    encountered = []
    with pgn_stream(path) as stream:
        while (game := chess.pgn.read_game(stream, Visitor=lambda: SelectedGameBuilder(selected))) is not None:
            if game_id(game.headers) in selected:
                encountered.append(game)
                assert list(game.mainline_moves())
    assert len(encountered) == 10
    assert any(int(game.headers["Round"]) >= 15 for game in encountered)
    cfg = {"seed": 1, "min_ply": 1, "max_ply": 180, "ply_gap": 2, "positions_per_game": 3}
    assert positions_from_game(encountered[0], cfg) == positions_from_game(encountered[0], cfg)
    assert 0 < len(positions_from_game(encountered[0], cfg)) <= 3


def test_sparse_model_matches_explicit_sum_and_backprop():
    torch.manual_seed(4)
    model = NNUE(16, 8)
    board = chess.Board()
    x = torch.from_numpy(encode(board)[None])
    output = model(x)
    accumulators = [model.bias + model.transform.weight[active_features(board, c)].sum(dim=0) for c in (board.turn, not board.turn)]
    expected = model.fc2(model.fc1(torch.cat(accumulators).clamp(0, 1)).clamp(0, 1)).squeeze()
    torch.testing.assert_close(output[0], expected)
    (output - 0.5).square().mean().backward()
    assert model.transform.weight.grad is not None
    assert model.transform.weight.grad[PADDING].abs().sum() == 0


def test_teacher_pov_mate_and_retry(monkeypatch):
    class FakeEngine:
        def __init__(self):
            self.calls = 0
        def configure(self, options):
            assert "Clear Hash" in options
        def analyse(self, board, limit, game):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("injected interruption")
            return {"score": chess.engine.PovScore(chess.engine.Mate(2), chess.WHITE), "depth": 3, "nodes": 100}
        def close(self):
            pass
    engine = FakeEngine()
    worker = Worker(Path("unused"), {"nodes": 100})
    monkeypatch.setattr(worker, "engine", lambda: engine)
    board = chess.Board()
    board.turn = chess.BLACK
    result = worker(("position", board.fen(), 0))
    assert result[1] == -2000 and result[2] == -2 and result[5] == 2


def test_export_rejects_corrupt_payload(tmp_path):
    import hashlib
    import struct
    from stockbear.features import FEATURE_VERSION
    payload = np.zeros(1, dtype="<f4").tobytes()
    header = {"feature_version": FEATURE_VERSION, "payload_sha256": hashlib.sha256(payload).hexdigest(),
              "tensors": [{"name": "one", "shape": [1], "offset": 0, "dtype": "<f4"}]}
    encoded = json.dumps(header).encode()
    path = tmp_path / "test.sbnnue"
    path.write_bytes(MAGIC + struct.pack("<I", len(encoded)) + encoded + payload)
    assert load_export(path)[1]["one"][0] == 0
    damaged = bytearray(path.read_bytes())
    damaged[-1] ^= 1
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="checksum"):
        load_export(path)


@pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA unavailable")
def test_cuda_sparse_training_and_cpu_parity():
    from stockbear.train import seed_everything
    seed_everything(91)
    model = NNUE(32, 8).cuda()
    x = torch.from_numpy(np.stack([encode(chess.Board())] * 8)).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.003, fused=True)
    for _ in range(2):
        optimizer.zero_grad(set_to_none=True)
        loss = (model(x).sigmoid() - 0.8).square().mean()
        loss.backward()
        optimizer.step()
    assert torch.isfinite(loss)
    with torch.inference_mode():
        expected = model(x).cpu()
        actual = model.cpu()(x.cpu())
    torch.testing.assert_close(expected, actual, atol=1e-6, rtol=1e-5)
