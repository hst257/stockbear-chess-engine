#pragma once

#include <cstdlib>

#include "evaluation.hpp"
#include "transposition.hpp"

namespace chesslab {

inline bool null_move_allowed(const chess::Board& board, int depth, int ply,
                               int alpha, int beta, bool null_subtree) {
    if (null_subtree || depth < 3 || ply == 0 || beta - alpha != 1 || board.inCheck() ||
        std::abs(alpha) >= MATE_THRESHOLD || std::abs(beta) >= MATE_THRESHOLD ||
        board.halfMoveClock() >= 90 || board.isRepetition(1) || game_phase(board) < 8) return false;
    for (const auto side : {chess::Color::WHITE, chess::Color::BLACK}) {
        const auto non_pawns = board.pieces(chess::PieceType::KNIGHT, side) |
            board.pieces(chess::PieceType::BISHOP, side) |
            board.pieces(chess::PieceType::ROOK, side) | board.pieces(chess::PieceType::QUEEN, side);
        if (non_pawns.count() < 2) return false;
    }
    return true;
}

inline bool lmr_candidate(const chess::Board& board, chess::Move move, int depth,
                           int ply, int move_index, int alpha, int beta,
                           chess::Move table_move, chess::Move pv_move, bool null_subtree) {
    if (null_subtree || depth < 3 || ply == 0 || move_index < 4 || beta - alpha != 1 ||
        board.inCheck() || game_phase(board) < 4 || std::abs(alpha) >= MATE_THRESHOLD ||
        std::abs(beta) >= MATE_THRESHOLD || move == table_move || move == pv_move ||
        board.isCapture(move) || move.typeOf() == chess::Move::PROMOTION ||
        move.typeOf() == chess::Move::CASTLING) return false;
    return board.givesCheck(move) == chess::CheckType::NO_CHECK;
}

}  // namespace chesslab
