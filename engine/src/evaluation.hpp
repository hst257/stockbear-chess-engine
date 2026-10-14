#pragma once

#include <array>

#include "chess.hpp"

namespace chesslab {

inline constexpr std::array<int, 7> PIECE_VALUES = {100, 320, 330, 500, 900, 0, 0};
inline constexpr std::array<int, 6> PHASE_WEIGHTS = {0, 1, 1, 2, 4, 0};
inline constexpr int MAX_PHASE = 24;

struct Evaluation {
    int material = 0;
    std::array<int, 6> pst{};  // White minus Black, indexed by PieceType.
    int phase = 0;

    int positional() const;
    int total() const { return material + positional(); }
};

int evaluate_material(const chess::Board& board);
int game_phase(const chess::Board& board);
Evaluation evaluate_breakdown(const chess::Board& board, bool use_pst = true);
int evaluate(const chess::Board& board, bool use_pst = true);

}  // namespace chesslab
