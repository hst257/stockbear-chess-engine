#pragma once

#include <array>
#include <cstdint>
#include "chess.hpp"

namespace chesslab {

constexpr int NNUE_MAX_WIDTH = 256;
struct NnueFeatures {
    std::array<std::array<std::uint16_t, 37>, 2> active{}; // Fixed White, Black order.
    int count = 0;
};
struct NnueAccumulator {
    std::array<std::array<float, NNUE_MAX_WIDTH>, 2> values{};
    NnueFeatures features;
};
// Piece changes captured BEFORE makeMove. State features are checked after it.
struct NnueDelta {
    std::array<std::uint16_t, 4> removed{}, added{}; // White-perspective indices.
    int removed_count = 0, added_count = 0;
};

NnueFeatures nnue_features(const chess::Board& board);
void nnue_refresh(const chess::Board& board, NnueAccumulator& output);
void nnue_update(const NnueAccumulator& parent, const chess::Board& board, NnueAccumulator& output);
NnueDelta nnue_move_delta(const chess::Board& before, chess::Move move);
void nnue_update_move(const NnueAccumulator& parent, const chess::Board& after,
                      const NnueDelta& delta, NnueAccumulator& output);
float nnue_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator);
int nnue_white_score(const chess::Board& board, const NnueAccumulator& accumulator);
int nnue_width();
int nnue_hidden();
const char* nnue_model_name();
const char* nnue_model_sha256();
// Selection is local to the calling thread; workers receive their own setting.
void nnue_set_kernel(const std::string& name);
const char* nnue_kernel();
float nnue_reference_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator);

}  // namespace chesslab
