#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

#include "chess.hpp"
#include "evaluation.hpp"
#include "profiling.hpp"
#include "diagnostics.hpp"
#include "transposition.hpp"

namespace chesslab {

struct NnueV3Model;

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
    bool aspiration_windows = true;
    int aspiration_delta = 25;  // Initial margin in centipawns, clamped to 1..500.
    bool null_move_pruning = true;
    bool late_move_reductions = true;
    int lmr_reduction = 1;  // Configurable 1..3, also clamped to depth - 2.
    EvaluationOptions evaluation;
    bool pawn_cache = true;
    bool fast_movegen = true;
    bool history_heuristic = true;
    bool killer_heuristic = true;
    bool static_exchange = true;
    bool adaptive_lmr = true;
    bool reverse_futility = true;
    bool futility = true;
    bool check_extensions = true;
    bool use_nnue = false;
    std::shared_ptr<const NnueV3Model> nnue_v3; // Immutable snapshot, absent for classical/v2.
    bool nnue_incremental = true;
    std::string nnue_kernel = "auto";
};

struct SearchResult {
#ifdef CHESSLAB_DIAGNOSTICS
    diagnostics::Report diagnostics;
#endif
    profiling::Report profile;
    std::uint64_t eval_calls = 0;
    std::uint64_t beta_cutoffs = 0;
    std::uint64_t pawn_probes = 0, pawn_hits = 0;
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
    std::uint64_t aspiration_attempts = 0;
    std::uint64_t aspiration_searches = 0;
    std::uint64_t aspiration_fail_high = 0;
    std::uint64_t aspiration_fail_low = 0;
    std::uint64_t aspiration_retries = 0;
    std::uint64_t aspiration_successes = 0;
    std::uint64_t null_attempts = 0;
    std::uint64_t null_cutoffs = 0;
    std::uint64_t lmr_attempts = 0;
    std::uint64_t lmr_searches = 0;
    std::uint64_t lmr_researches = 0;
    std::uint64_t lmr_verifications = 0;
    std::uint64_t history_updates = 0, killer_cutoffs = 0, see_calls = 0;
    std::uint64_t reverse_futility_cutoffs = 0, futility_prunes = 0, check_extensions = 0;
    std::uint64_t nnue_evaluations = 0;
};

using SearchProgress = std::function<void(const SearchResult&)>;
SearchResult search(chess::Board board, const SearchLimits& limits,
                    bool alpha_beta, const std::atomic<bool>& stop,
                    const SearchProgress& progress = {});
std::uint64_t perft(chess::Board& board, int depth);

}  // namespace chesslab
