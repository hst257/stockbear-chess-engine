#pragma once

#include <array>
#include <cstdint>
#include <string>
#include "chess.hpp"
#include "nnue_dimensions.hpp"

namespace chesslab {

constexpr int NNUE_MAX_WIDTH = 256;
struct NnueFeatures {
    std::array<std::array<std::uint16_t, 37>, 2> active{}; // Fixed White, Black order.
    int count = 0;
};
struct NnueAccumulator {
    std::array<std::array<float, NNUE_WIDTH>, 2> values{};
    // Experimental integer state. Only the selected representation is updated.
    std::array<std::array<std::int32_t, NNUE_WIDTH>, 2> quantized{};
    NnueFeatures features;
};
// Piece changes captured BEFORE makeMove. State features are checked after it.
struct NnueDelta {
    std::array<std::uint16_t, 4> removed{}, added{}; // White-perspective indices.
    int removed_count = 0, added_count = 0;
};

#ifndef CHESSLAB_NNUE_UPDATE
#define CHESSLAB_NNUE_UPDATE 2
#endif
// Search-only contract: legal move-derived deltas, distinct child storage, and
// no generic feature-diff update on a compact child. Roots always refresh fully.
// Compact children retain sorted state features only; float sums remain complete.
void nnue_update_search(const NnueAccumulator& parent, const chess::Board& after,
                        const NnueDelta& delta, NnueAccumulator& output);
#if CHESSLAB_NNUE_UPDATE > 0
struct NnueStateFeatures {
    std::array<std::array<std::uint16_t, 5>, 2> active{};
    int count = 0;  // Four orthodox castling rights plus one legal EP file.
};
#if CHESSLAB_NNUE_UPDATE == 5
using NnueSearchFeatures = NnueStateFeatures;
#else
using NnueSearchFeatures = NnueFeatures;
#endif
NnueSearchFeatures nnue_search_states(const chess::Board& board);
void nnue_update_search_states(const NnueAccumulator& parent, const NnueSearchFeatures& states,
                               const NnueDelta& delta, NnueAccumulator& output);
#endif

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
bool nnue_simd_available();
const char* nnue_effective_kernel();
bool nnue_quantized();
int nnue_quant_first_scale();
float nnue_reference_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator);

}  // namespace chesslab
