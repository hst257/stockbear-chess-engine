import hashlib
import struct

import chess
import numpy as np
import pytest
import torch

from stockbear.features import encode as encode_v2
from stockbear.v3.features import FEATURES, PADDING, encode, from_v2
from stockbear.v3.model import KingRelativeNNUE
from stockbear.v3.export import HEADER, read_model, write_model


@pytest.mark.parametrize("buckets", [16, 64])
@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
    "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
    "7k/4P3/8/8/8/8/8/K7 w - - 0 1",
    "4r2k/8/8/2PpP3/8/8/8/4K3 w - d6 0 1"])
def test_sparse_conversion_and_color_symmetry(fen, buckets):
    board = chess.Board(fen)
    assert np.array_equal(encode(board, buckets), from_v2(encode_v2(board)[None], buckets)[0])
    assert np.array_equal(encode(board, buckets), encode(board.mirror(), buckets))
    for move in list(board.legal_moves):
        child = board.copy()
        child.push(move)
        assert np.array_equal(encode(child, buckets), from_v2(encode_v2(child)[None], buckets)[0])


def test_king_conditioning_changes_piece_rows():
    a = chess.Board("7k/8/8/8/8/8/P7/K7 w - - 0 1")
    b = chess.Board("7k/8/8/8/8/8/P7/1K6 w - - 0 1")
    assert encode(a)[0, 0] != encode(b)[0, 0]
    assert encode(a)[1, 0] == encode(b)[1, 0]
    with pytest.raises(ValueError):
        encode(chess.Board.empty())


def test_format_round_trip_and_integrity(tmp_path):
    model = KingRelativeNNUE()
    assert sum(p.numel() for p in model.parameters()) == 1312225
    path = tmp_path / "model.sbnnue"
    write_model(path, model)
    arrays = read_model(path)
    assert arrays["transform.weight"].shape == (FEATURES + 1, 32)
    assert not arrays["transform.weight"][PADDING].any()
    damaged = bytearray(path.read_bytes())
    struct.pack_into("<f", damaged, HEADER.size, float("nan"))
    damaged[40:72] = hashlib.sha256(damaged[72:]).digest()
    path.write_bytes(damaged)
    with pytest.raises(ValueError, match="Nonfinite"):
        read_model(path)
