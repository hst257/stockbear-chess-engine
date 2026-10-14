#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <vector>

#include "chess.hpp"
#include "evaluation.hpp"
#include "transposition.hpp"

namespace chesslab {

struct SearchLimits {
    int depth = 3;
    std::uint64_t nodes = 0;  // Zero means no node limit.
    int milliseconds = 0;    // Zero means no time limit.
    bool iterative_deepening = true;
    bool move_ordering = true;
    bool use_pst = true;
    bool transposition_table = true;
    int hash_megabytes = 16;
    std::uint64_t history = 0;  // Reversible pre-root history, maintained with next_history().
    bool quiescence = true;
    bool principal_variation_search = true;  // Effective only with alpha-beta enabled.
    bool time_managed = false;  // Movetime without depth: deepen to the safety ceiling.
};

struct SearchResult {
    chess::Move best_move{};
    std::vector<chess::Move> pv;
    int white_score = 0;
    int depth = 0;       // Deepest fully completed iteration; zero is a fallback.
    int selective_depth = 0;
    std::uint64_t nodes = 0;
    std::int64_t milliseconds = 0;
    bool complete = false;  // The requested target depth was reached.
    std::uint64_t tt_probes = 0;
    std::uint64_t tt_hits = 0;
    std::uint64_t tt_cutoffs = 0;
    int hashfull = 0;  // Permille of occupied slots.
    std::uint64_t qnodes = 0;  // Included in nodes, not additional to them.
    std::uint64_t pvs_scouts = 0;
    std::uint64_t pvs_researches = 0;
    std::uint64_t qcaps = 0;
    bool ply_limit_reached = false;
};

using SearchProgress = std::function<void(const SearchResult&)>;
SearchResult search(chess::Board board, const SearchLimits& limits,
                    bool alpha_beta, const std::atomic<bool>& stop,
                    const SearchProgress& progress = {});
std::uint64_t perft(chess::Board& board, int depth);

}  // namespace chesslab
