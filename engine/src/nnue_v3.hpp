#pragma once

#include <array>
#include <memory>
#include <string>
#include <vector>
#include "chess.hpp"
#include "nnue.hpp"

namespace chesslab {
constexpr int V3_PIECE_FEATURES = 40960;
constexpr int V3_FEATURES = 40972;
constexpr int V3_WIDTH = 32;
constexpr int V3_HIDDEN = 16;
constexpr int V3_MAX_ACTIVE = 35;

struct NnueV3Model {
    int king_buckets = 64;
    int features = V3_FEATURES;
    std::vector<float> weights;
    std::array<std::array<float, 16>, 64> head;
    std::string payload_sha256;
    const float* row(int index) const { return weights.data() + 32 + index * 32; }
    int king_index(int square) const { return king_buckets == 64 ? square : (square / 16) * 4 + square % 8 / 2; }
};
struct NnueV3Features {
    std::array<std::array<int, V3_MAX_ACTIVE>, 2> active{};
    int count = 0;
};
struct NnueV3Frame {
    std::array<std::array<float, 32>, 2> values{}; // Unclipped, fixed White/Black.
    std::array<int, 2> kings{}; // Perspective-oriented king squares.
    std::array<std::array<int, 5>, 2> states{};
    int state_count = 0;
};

std::shared_ptr<const NnueV3Model> nnue_v3_load(const std::string& path);
NnueV3Features nnue_v3_features(const chess::Board& board, int king_buckets = 64);
void nnue_v3_refresh(const NnueV3Model& model, const chess::Board& board, NnueV3Frame& out);
void nnue_v3_update(const NnueV3Model& model, const NnueV3Frame& parent,
                    const chess::Board& after, const NnueDelta& delta, NnueV3Frame& out);
float nnue_v3_side_to_move(const NnueV3Model& model, const chess::Board& board, const NnueV3Frame& frame);
int nnue_v3_white_score(const NnueV3Model& model, const chess::Board& board, const NnueV3Frame& frame);
} // namespace chesslab
