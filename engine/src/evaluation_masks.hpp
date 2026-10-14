#pragma once

#include <array>
#include <cstdint>

namespace chesslab::eval_masks {

constexpr std::uint64_t file(int f) { return 0x0101010101010101ULL << f; }
constexpr std::uint64_t adjacent(int f) {
    return (f > 0 ? file(f - 1) : 0) | (f < 7 ? file(f + 1) : 0);
}
// Indexed by color (White=0) and native A1=0 square. No runtime allocation.
constexpr auto forward_masks() {
    std::array<std::array<std::uint64_t, 64>, 2> result{};
    for (int color = 0; color < 2; ++color)
        for (int sq = 0; sq < 64; ++sq)
            for (int r = 0; r < 8; ++r)
                if (color == 0 ? r > sq / 8 : r < sq / 8)
                    result[color][sq] |= 0xFFULL << (8 * r);
    return result;
}
inline constexpr auto FORWARD = forward_masks();
inline constexpr std::uint64_t CENTER = 0x0000001818000000ULL;  // d4/e4/d5/e5
inline constexpr std::uint64_t WHITE_SPACE = 0x00003C3C3C000000ULL;  // c4..f6
inline constexpr std::uint64_t BLACK_SPACE = 0x0000003C3C3C0000ULL;  // c3..f5

}  // namespace chesslab::eval_masks
