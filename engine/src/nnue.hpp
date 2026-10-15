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

NnueFeatures nnue_features(const chess::Board& board);
void nnue_refresh(const chess::Board& board, NnueAccumulator& output);
void nnue_update(const NnueAccumulator& parent, const chess::Board& board, NnueAccumulator& output);
float nnue_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator);
int nnue_white_score(const chess::Board& board, const NnueAccumulator& accumulator);
int nnue_width();
int nnue_hidden();
const char* nnue_model_name();
const char* nnue_model_sha256();

}  // namespace chesslab
