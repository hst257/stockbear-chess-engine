#pragma once

#include <array>
#include <chrono>
#include <cstdint>

namespace chesslab::profiling {
enum Category { SEARCH, MOVEGEN, EVALUATION, ORDERING, MAKE, UNMAKE, TABLE, DRAWS,
                POLICY, PAWNS, ATTACKS, MATERIAL_PST, KING_SAFETY, ENDGAME,
                NNUE_FEATURES, NNUE_REFRESH, NNUE_UPDATE, NNUE_HEAD,
#ifdef CHESSLAB_DIAGNOSTICS
                NNUE_COPY,
                NNUE_DELTA, NNUE_STATE, NNUE_METADATA, NNUE_ROWS,
#endif
                COUNT };
inline constexpr std::array<const char*, COUNT> NAMES = {
    "search_other", "movegen", "evaluation_other", "ordering", "make", "unmake", "table", "draws",
    "search_policy", "pawn_evaluation", "attack_maps", "material_pst", "king_safety", "endgame",
    "nnue_features", "nnue_refresh", "nnue_update", "nnue_head"
#ifdef CHESSLAB_DIAGNOSTICS
    , "nnue_copy"
    , "nnue_delta", "nnue_state", "nnue_metadata", "nnue_rows"
#endif
};
struct Report {
    std::array<std::uint64_t, COUNT> ns{};
    std::array<std::uint64_t, COUNT> calls{};
    std::uint64_t allocations = 0, bytes = 0;
};
#ifdef CHESSLAB_PROFILE
using Clock = std::chrono::steady_clock;
inline thread_local Report report;
inline thread_local bool active = false;
inline thread_local int current = COUNT;
inline thread_local Clock::time_point last;
inline void reset() { report = {}; current = COUNT; active = true; last = Clock::now(); }
inline Report finish() {
    if (active && current < COUNT) report.ns[current] +=
        std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - last).count();
    active = false;
    return report;
}
class Scope {
    int previous_;
public:
    explicit Scope(Category category) : previous_(current) {
        if (!active) return;
        const auto now = Clock::now();
        if (current < COUNT) report.ns[current] += std::chrono::duration_cast<std::chrono::nanoseconds>(now - last).count();
        current = category;
        last = now;
        ++report.calls[category];
    }
    ~Scope() {
        if (!active) return;
        const auto now = Clock::now();
        report.ns[current] += std::chrono::duration_cast<std::chrono::nanoseconds>(now - last).count();
        current = previous_;
        last = now;
    }
};
#else
inline void reset() {}
inline Report finish() { return {}; }
class Scope { public: explicit Scope(Category) {} };
#endif
}  // namespace chesslab::profiling
