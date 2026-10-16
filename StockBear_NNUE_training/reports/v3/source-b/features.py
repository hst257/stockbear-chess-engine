"""Normalized full king-conditioned pieces and independent v2 state inputs."""
from __future__ import annotations

import chess
import numpy as np

FEATURE_VERSION = "halfkp64-10x64-shared-state12-v3"
PIECE_FEATURES = 40960
FEATURES = PIECE_FEATURES + 12
PADDING = FEATURES
MAX_ACTIVE = 35


def feature_count(king_buckets: int = 64) -> int:
    if king_buckets not in (16, 64):
        raise ValueError("Only the planned 64-square or 16-bucket contracts are supported")
    return king_buckets * 640 + 12


def active_features(board: chess.Board, perspective: chess.Color, king_buckets: int = 64) -> list[int]:
    if not board.is_valid() or board.chess960:
        raise ValueError("V3 requires a valid orthodox chess position")
    mirror = 0 if perspective == chess.WHITE else 56
    king = board.king(perspective) ^ mirror
    base = feature_count(king_buckets) - 12
    if king_buckets == 16:
        king = (king // 8 // 2) * 4 + king % 8 // 2
    result = []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        category = (0 if piece.color == perspective else 5) + piece.piece_type - 1
        result.append((king * 10 + category) * 64 + (square ^ mirror))
    for relative, color in enumerate((perspective, not perspective)):
        if board.has_kingside_castling_rights(color):
            result.append(base + relative * 2)
        if board.has_queenside_castling_rights(color):
            result.append(base + relative * 2 + 1)
    if board.has_legal_en_passant():
        result.append(base + 4 + chess.square_file(board.ep_square))
    return sorted(result)


def encode(board: chess.Board, king_buckets: int = 64) -> np.ndarray:
    result = np.full((2, MAX_ACTIVE), feature_count(king_buckets), dtype=np.uint16)
    for i, color in enumerate((board.turn, not board.turn)):
        active = active_features(board, color, king_buckets)
        if len(active) > MAX_ACTIVE:
            raise ValueError("Too many active features")
        result[i, :len(active)] = active
    return result


def from_v2(values: np.ndarray, king_buckets: int = 64) -> np.ndarray:
    """Re-encode audited sparse v2 rows without altering target/split ordering."""
    x = np.asarray(values, dtype=np.int32)
    if x.ndim != 3 or x.shape[1:] != (2, 37) or np.any((x < 0) | (x > 780)):
        raise ValueError("Invalid v2 sparse features")
    own_king = (x >= 320) & (x < 384)
    other_king = (x >= 704) & (x < 768)
    if np.any(own_king.sum(axis=2) != 1) or np.any(other_king.sum(axis=2) != 1):
        raise ValueError("Each perspective requires exactly two kings")
    king = np.where(own_king, x - 320, 0).sum(axis=2)
    padding = feature_count(king_buckets)
    if king_buckets == 16:
        king = (king // 16) * 4 + king % 8 // 2
    pieces = (x < 768) & (x // 64 % 6 != 5)
    transformed = ((king[:, :, None] * 10 + x // 384 * 5 + x // 64 % 6) * 64 + x % 64)
    state = (x >= 768) & (x < 780)
    rows = np.where(pieces, transformed, np.where(state, padding - 12 + x - 768, padding))
    rows.sort(axis=2)
    if np.any(rows[:, :, MAX_ACTIVE:] != padding):
        raise ValueError("V3 active feature capacity exceeded")
    return rows[:, :, :MAX_ACTIVE].astype(np.uint16)
