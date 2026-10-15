#pragma once

#include <algorithm>
#include <array>
#include "evaluation.hpp"
#include "transposition.hpp"

namespace chesslab {

// Private to one search. Gravity updates bound history and age old evidence.
struct OrderingHistory {
    std::array<std::array<std::array<int, 64>, 64>, 2> quiet{};
    std::array<std::array<chess::Move, 2>, MAX_SEARCH_PLY + 1> killers{};

    int score(const chess::Board& board, chess::Move move) const {
        return quiet[board.sideToMove() == chess::Color::WHITE ? 0 : 1][move.from().index()][move.to().index()];
    }
    bool killer(chess::Move move, int ply) const {
        return ply <= MAX_SEARCH_PLY && (killers[ply][0] == move || killers[ply][1] == move);
    }
    void update(const chess::Board& board, chess::Move move, int bonus) {
        auto& value = quiet[board.sideToMove() == chess::Color::WHITE ? 0 : 1][move.from().index()][move.to().index()];
        bonus = std::clamp(bonus, -2048, 2048);
        value += bonus - value * std::abs(bonus) / 8192;
    }
    void cutoff(const chess::Board& board, chess::Move move, int ply, int depth,
                const chess::Movelist& unsuccessful, bool use_history, bool use_killers) {
        if (use_killers && ply <= MAX_SEARCH_PLY && killers[ply][0] != move) {
            killers[ply][1] = killers[ply][0];
            killers[ply][0] = move;
        }
        if (!use_history) return;
        const int bonus = std::min(2048, 32 * depth * depth);
        update(board, move, bonus);
        for (auto previous : unsuccessful) update(board, previous, -bonus / 2);
    }
};

// Swap-off analysis on local bitboards: recompute x-rays, reject pinned
// recaptures and illegal king captures, handle EP and promotion material.
// Like conventional LVA SEE this is an ordering estimate, never a search proof.
inline int static_exchange(const chess::Board& board, chess::Move move) {
    if (move.typeOf() == chess::Move::CASTLING) return 0;
    std::array<std::array<chess::Bitboard, 6>, 2> pieces{};
    for (int c = 0; c < 2; ++c)
        for (int k = 0; k < 6; ++k)
            pieces[c][k] = board.pieces(chess::PieceType(static_cast<chess::PieceType::underlying>(k)),
                                       c == 0 ? chess::Color::WHITE : chess::Color::BLACK);
    auto occupied = board.occ();
    const int to = move.to().index(), from = move.from().index();
    const auto target = chess::Bitboard::fromSquare(to);
    int side = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
    int occupant = static_cast<int>(board.at<chess::PieceType>(move.from()));
    const int victim = static_cast<int>(board.getCapturing<chess::PieceType>(move));
    int gains[32]{};
    gains[0] = PIECE_VALUES[victim];
    pieces[side][occupant] &= ~chess::Bitboard::fromSquare(from);
    occupied &= ~chess::Bitboard::fromSquare(from);
    if (board.isCapture(move)) {
        const int captured = move.typeOf() == chess::Move::ENPASSANT ? to + (side == 0 ? -8 : 8) : to;
        pieces[1 - side][victim] &= ~chess::Bitboard::fromSquare(captured);
        occupied &= ~chess::Bitboard::fromSquare(captured);
    }
    if (move.typeOf() == chess::Move::PROMOTION) {
        occupant = static_cast<int>(move.promotionType());
        gains[0] += PIECE_VALUES[occupant] - PIECE_VALUES[0];
    }
    pieces[side][occupant] |= target;
    occupied |= target;
    auto attackers = [&](int c, int square) {
        const auto sq = chess::Square(square);
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        return (chess::attacks::pawn(~color, sq) & pieces[c][0]) |
               (chess::attacks::knight(sq) & pieces[c][1]) |
               (chess::attacks::bishop(sq, occupied) & (pieces[c][2] | pieces[c][4])) |
               (chess::attacks::rook(sq, occupied) & (pieces[c][3] | pieces[c][4])) |
               (chess::attacks::king(sq) & pieces[c][5]);
    };
    int depth = 0;
    while (depth < 31 && occupant != 5) {
        side = 1 - side;
        const auto available = attackers(side, to);
        int selected = -1, kind = 0, promoted = 0;
        for (; kind < 6 && selected < 0; ++kind) {
            auto candidates = available & pieces[side][kind];
            while (candidates) {
                const int sq = candidates.pop();
                const auto bit = chess::Bitboard::fromSquare(sq);
                promoted = kind == 0 && (to / 8 == 0 || to / 8 == 7) ? 4 : kind;
                pieces[1 - side][occupant] &= ~target;
                pieces[side][kind] &= ~bit;
                pieces[side][promoted] |= target;
                occupied &= ~bit;
                const int king = pieces[side][5].lsb();
                const bool legal = !attackers(1 - side, king);
                occupied |= bit;
                pieces[side][promoted] &= ~target;
                pieces[side][kind] |= bit;
                pieces[1 - side][occupant] |= target;
                if (legal) { selected = sq; break; }
            }
        }
        if (selected < 0) break;
        --kind;
        const int promotion_gain = promoted != kind ? PIECE_VALUES[promoted] - PIECE_VALUES[kind] : 0;
        ++depth;
        gains[depth] = PIECE_VALUES[occupant] + promotion_gain - gains[depth - 1];
        const auto source = chess::Bitboard::fromSquare(selected);
        pieces[1 - side][occupant] &= ~target;
        pieces[side][kind] &= ~source;
        pieces[side][promoted] |= target;
        occupied &= ~source;
        occupant = promoted;
    }
    while (depth > 0) {
        gains[depth - 1] = -std::max(-gains[depth - 1], gains[depth]);
        --depth;
    }
    return gains[0];
}

inline int adaptive_reduction(int depth, int move_index, int history, int base) {
    int reduction = base + (depth >= 6) + (depth >= 10) + (move_index >= 8) + (move_index >= 16);
    if (history > 1024) --reduction;
    if (history < -1024) ++reduction;
    return std::clamp(reduction, 1, std::min(4, depth - 2));
}

}  // namespace chesslab
