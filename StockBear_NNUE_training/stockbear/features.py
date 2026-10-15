from __future__ import annotations

import chess
import numpy as np

FEATURES = 780
PADDING = FEATURES
MAX_ACTIVE = 37  # 32 pieces + 4 castling rights + 1 legal EP file.
FEATURE_VERSION = "dual-perspective-12x64-castling-ep-v1"


def active_features(board: chess.Board, perspective: chess.Color) -> list[int]:
    features = []
    for square, piece in board.piece_map().items():
        oriented = square if perspective == chess.WHITE else square ^ 56
        relative_color = 0 if piece.color == perspective else 1
        features.append((relative_color * 6 + piece.piece_type - 1) * 64 + oriented)
    for relative_color, color in enumerate((perspective, not perspective)):
        if board.has_kingside_castling_rights(color):
            features.append(768 + relative_color * 2)
        if board.has_queenside_castling_rights(color):
            features.append(769 + relative_color * 2)
    if board.has_legal_en_passant():
        features.append(772 + chess.square_file(board.ep_square))
    return sorted(features)


def encode(board: chess.Board) -> np.ndarray:
    result = np.full((2, MAX_ACTIVE), PADDING, dtype=np.int64)
    # Ordering rather than feature bits carries side to move.
    for i, color in enumerate((board.turn, not board.turn)):
        active = active_features(board, color)
        result[i, :len(active)] = active
    return result


def update_accumulator(accumulator, before: chess.Board, after: chess.Board, perspective: bool, weights):
    old, new = set(active_features(before, perspective)), set(active_features(after, perspective))
    result = accumulator.copy()
    for index in old - new:
        result -= weights[index]
    for index in new - old:
        result += weights[index]
    return result
