#pragma once
// Experimental input transformation only. Keep all dense/output additions in
// their frozen order. This header is linked only into the isolated source copy.
#include "nnue.hpp"
#include "nnue_weights.hpp"
#include <algorithm>

#if (defined(__x86_64__) || defined(__i386__)) && (defined(__GNUC__) || defined(__clang__))
#include <immintrin.h>
namespace chesslab::stage1 {

// MAX/MIN return the second operand for unordered/equal comparisons. Keeping
// the input there preserves std::clamp's NaN payload and negative-zero bits.
__attribute__((target("avx2")))
inline void clip_inputs(const float* source, float* destination, int count) {
    const auto zero = _mm256_setzero_ps();
    const auto one = _mm256_set1_ps(1.0f);
    for (int j = 0; j < count; j += 8) {
        const auto input = _mm256_loadu_ps(source + j);
        const auto lower = _mm256_max_ps(zero, input);
        _mm256_storeu_ps(destination + j, _mm256_min_ps(one, lower));
    }
}

__attribute__((target("avx2")))
inline float head(const chess::Board& board, const NnueAccumulator& accumulator) {
    namespace w = nnue_weights;
    static_assert(w::WIDTH % 8 == 0, "Vector clipping requires complete lanes");
    alignas(64) float input[2 * w::WIDTH];
    alignas(64) float hidden[w::HIDDEN];
    const int first = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
    clip_inputs(accumulator.values[first].data(), input, w::WIDTH);
    clip_inputs(accumulator.values[1 - first].data(), input + w::WIDTH, w::WIDTH);
    std::copy_n(w::fc1_bias, w::HIDDEN, hidden);
    // Flattening the two perspective loops retains their exact input order.
    for (int j = 0; j < 2 * w::WIDTH; ++j) {
        const auto* weights = w::fc1_transposed + j * w::HIDDEN;
        for (int h = 0; h < w::HIDDEN; ++h) hidden[h] += weights[h] * input[j];
    }
    float output = w::fc2_bias[0];
    for (int h = 0; h < w::HIDDEN; ++h)
        output += w::fc2_weight[h] * std::clamp(hidden[h], 0.0f, 1.0f);
    return output * 400.0f;
}
}  // namespace chesslab::stage1
#endif
