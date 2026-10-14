#pragma once

#include <array>
#include <cstdint>

#include "evaluation.hpp"

namespace chesslab {

// Only pawn-dependent information. Occupancy, kings, phase, shelter, blocked
// paths and option-specific scores are deliberately absent from this entry.
struct PawnData {
    chess::Bitboard pawns[2];
    chess::Bitboard attacks[2];
    chess::Bitboard double_attacks[2];
    chess::Bitboard passers[2];
    chess::Bitboard backward[2];
    EvalScore structure;
    bool valid = false;
};

class PawnCache {
    std::array<PawnData, 1024> entries_;
public:
    std::uint64_t probes = 0, hits = 0;
    const PawnData& get(chess::Bitboard white, chess::Bitboard black);
};

}  // namespace chesslab
