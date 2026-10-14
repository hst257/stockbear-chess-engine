#pragma once

#include "chess.hpp"

namespace chesslab {

// The pinned library handles same-color bishop draws only up to four pieces.
// Promotions can produce more bishops without making mate possible. Keep this
// rules correction outside immutable vendor code; two knights are not dead.
inline bool insufficient_material(const chess::Board& board) {
    if (board.pieces(chess::PieceType::PAWN, chess::PieceType::ROOK, chess::PieceType::QUEEN)) return false;
    const auto bishops = board.pieces(chess::PieceType::BISHOP);
    const auto knights = board.pieces(chess::PieceType::KNIGHT);
    if ((bishops | knights).count() <= 1) return true;
    if (knights) return false;
    return !(bishops & 0x55AA55AA55AA55AAULL) || !(bishops & 0xAA55AA55AA55AA55ULL);
}

}  // namespace chesslab
