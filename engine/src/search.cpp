#include "search.hpp"
#include "scoped_move.hpp"
#include "search_policy.hpp"
#include "principal_variation.hpp"
#include "pawn_cache.hpp"
#include "terminal_rules.hpp"
#include "strength.hpp"
#include "nnue.hpp"

#include <algorithm>
#include <memory>

namespace chesslab {
namespace {

constexpr int INFINITY_SCORE = 32000;
constexpr int MAX_QUIESCENCE_PLY = 16;
struct Interrupted {};

void order_moves(chess::Movelist& moves, const chess::Board& board,
                 chess::Move pv_move, chess::Move table_move,
                 const OrderingHistory& history, const SearchLimits& limits,
                 SearchResult& result, int ply) {
    profiling::Scope measured(profiling::ORDERING);
    for (auto& move : moves) {
        int priority = 0;
        int capture_bonus = 0;
        if (board.isCapture(move)) {
            // MVV-LVA: most valuable victim, least valuable attacker. The rules
            // library handles en passant's empty destination and castling.
            capture_bonus = 10 * PIECE_VALUES[board.getCapturing<chess::PieceType>(move)] -
                            PIECE_VALUES[board.at<chess::PieceType>(move.from())];
            priority = 10000 + capture_bonus;
            if (limits.static_exchange) {
                ++result.see_calls;
                if (static_exchange(board, move) < 0) priority = -12000 + capture_bonus;
            }
        }
        if (move.typeOf() == chess::Move::PROMOTION) {
            priority = 20000 + PIECE_VALUES[move.promotionType()] + capture_bonus;
        }
        if (!board.isCapture(move) && move.typeOf() != chess::Move::PROMOTION) {
            if (limits.history_heuristic) priority = history.score(board, move) / 2;
            if (limits.killer_heuristic && history.killer(move, ply)) priority = 6000;
        }
        if (move == pv_move) priority = 32000;
        if (move == table_move) priority = 32500;
        move.setScore(static_cast<std::int16_t>(priority));
    }
    // Equal priorities preserve the library order, including quiet moves.
    // Stable insertion is allocation-free and nearly linear for the long runs
    // of equal-priority quiet moves returned by the rules library.
    for (auto i = moves.begin() + (moves.empty() ? 0 : 1); i != moves.end(); ++i) {
        const auto selected = *i;
        auto j = i;
        while (j != moves.begin() && (j - 1)->score() < selected.score()) {
            *j = *(j - 1);
            --j;
        }
        *j = selected;
    }
}

class Search {
public:
    Search(const SearchLimits& limits, bool pruning, const std::atomic<bool>& stop)
        : limits_(limits), pruning_(pruning), stop_(stop), start_(Clock::now()),
          deadline_(limits.milliseconds ? start_ + std::chrono::milliseconds(limits.milliseconds) : Clock::time_point::max()),
          table_(limits.transposition_table ? std::make_unique<TranspositionTable>(limits.hash_megabytes) : nullptr),
          pawn_cache_(limits.pawn_cache && limits.evaluation.advanced && !limits.use_nnue ? std::make_unique<PawnCache>() : nullptr) {}

    SearchResult run(chess::Board& board, const SearchProgress& progress) {
        nnue_set_kernel(limits_.nnue_kernel);
        profiling::reset();
        profiling::Scope measured(profiling::SEARCH);
#ifdef CHESSLAB_DIAGNOSTICS
        diagnostics::reset(limits_.use_nnue && limits_.nnue_incremental,
                           sizeof(NnueAccumulator), sizeof(std::array<NnueAccumulator, MAX_SEARCH_PLY + 1>));
#endif
        if (limits_.use_nnue && limits_.nnue_incremental) {
            nnue_stack_ = std::make_unique<std::array<NnueAccumulator, MAX_SEARCH_PLY + 1>>();
            nnue_refresh(board, (*nnue_stack_)[0]);
        }
        chess::Movelist moves;
        generate(moves, board);
        // If stopped before depth one finishes, still return a legal move.
        if (!moves.empty() && !is_draw(board)) result_.best_move = moves[0];
        const bool terminal = moves.empty() || is_draw(board);
        const int first = (limits_.iterative_deepening && !terminal) || (limits_.time_managed && terminal) ? 1 : limits_.depth;
        for (int depth = first; depth <= limits_.depth; ++depth) {
            // Only commit a complete pass. Recursive PV updates stay local, so an
            // interrupted deeper pass cannot corrupt the saved move or score.
            PrincipalVariation pv;
            int score;
            try {
                const bool aspiration = pruning_ && limits_.aspiration_windows &&
                    limits_.iterative_deepening && result_.depth > 0 &&
                    std::abs(result_.white_score) < MATE_THRESHOLD;
                int low_margin = std::clamp(limits_.aspiration_delta, 1, 500);
                int high_margin = low_margin;
                const int center = result_.white_score;
                int alpha = aspiration ? std::max(-INFINITY_SCORE, center - low_margin) : -INFINITY_SCORE;
                int beta = aspiration ? std::min(INFINITY_SCORE, center + high_margin) : INFINITY_SCORE;
                int retries = 0;
                if (aspiration) ++result_.aspiration_attempts;
                for (;;) {
                    check_limits(true);
                    pv.clear();
                    if (aspiration) ++result_.aspiration_searches;
                    score = minimax(board, depth, 0, alpha, beta, pv, true, limits_.history);
                    if ((score > alpha && score < beta) ||
                        (alpha == -INFINITY_SCORE && beta == INFINITY_SCORE)) break;
                    // A failed window proves only a bound. Widen that side;
                    // no failed move/score/PV is published as a completed pass.
                    if (score <= alpha) {
                        ++result_.aspiration_fail_low;
                        low_margin = std::min(2 * INFINITY_SCORE, low_margin * 2);
                        alpha = std::max(-INFINITY_SCORE, center - low_margin);
                    } else {
                        ++result_.aspiration_fail_high;
                        high_margin = std::min(2 * INFINITY_SCORE, high_margin * 2);
                        beta = std::min(INFINITY_SCORE, center + high_margin);
                    }
                    ++result_.aspiration_retries;
                    if (++retries >= 16 || std::abs(score) >= MATE_THRESHOLD) {
                        alpha = -INFINITY_SCORE;
                        beta = INFINITY_SCORE;
                    }
                }
                if (aspiration) ++result_.aspiration_successes;
            } catch (const Interrupted&) {
                break;
            }
            result_.white_score = score;
            pv.publish(result_.pv);
            result_.depth = depth;
            result_.complete = depth == limits_.depth;
            if (!result_.pv.empty()) result_.best_move = result_.pv.front();
            result_.milliseconds = elapsed();
            result_.hashfull = table_ ? table_->hashfull() : 0;
            if (pawn_cache_) { result_.pawn_probes = pawn_cache_->probes; result_.pawn_hits = pawn_cache_->hits; }
            if (progress) progress(result_);
            // Only time-managed searches stop on a proven root mate. Explicit
            // depth requests retain their reproducible target-depth behavior.
            if (limits_.time_managed && (terminal || std::abs(score) >= MATE_THRESHOLD)) break;
        }
        // Totals include unfinished work; depth/PV/score refer to the saved pass.
        result_.milliseconds = elapsed();
        result_.hashfull = table_ ? table_->hashfull() : 0;
        if (pawn_cache_) { result_.pawn_probes = pawn_cache_->probes; result_.pawn_hits = pawn_cache_->hits; }
#ifdef CHESSLAB_DIAGNOSTICS
        result_.diagnostics = diagnostics::finish();
#endif
        result_.profile = profiling::finish();
        return result_;
    }

private:
    using Clock = std::chrono::steady_clock;
    const SearchLimits& limits_;
    bool pruning_;
    const std::atomic<bool>& stop_;
    Clock::time_point start_;
    Clock::time_point deadline_;
    SearchResult result_;
    std::unique_ptr<TranspositionTable> table_;  // Fresh per search; shared across completed passes.
    std::unique_ptr<PawnCache> pawn_cache_;
    OrderingHistory ordering_;
    std::unique_ptr<std::array<NnueAccumulator, MAX_SEARCH_PLY + 1>> nnue_stack_;

    int static_evaluation(const chess::Board& board, int ply) {
        ++result_.eval_calls;
        profiling::Scope measured(profiling::EVALUATION);
        if (limits_.use_nnue) {
#ifdef CHESSLAB_DIAGNOSTICS
            diagnostics::evaluation(ply);
#endif
            ++result_.nnue_evaluations;
            if (nnue_stack_) return nnue_white_score(board, (*nnue_stack_)[ply]);
            NnueAccumulator fresh;
            nnue_refresh(board, fresh);
            return nnue_white_score(board, fresh);
        }
        return evaluate(board, limits_.use_pst, limits_.evaluation, pawn_cache_.get());
    }

    void descend_nnue(const chess::Board& board, int ply, const NnueDelta& delta = {}) {
        if (!nnue_stack_) return;
        if (limits_.nnue_kernel == "reference") nnue_update((*nnue_stack_)[ply - 1], board, (*nnue_stack_)[ply]);
        else nnue_update_move((*nnue_stack_)[ply - 1], board, delta, (*nnue_stack_)[ply]);
#ifdef CHESSLAB_DIAGNOSTICS
        diagnostics::prepare(ply);
#endif
    }

    void generate(chess::Movelist& moves, const chess::Board& board) {
        profiling::Scope measured(profiling::MOVEGEN);
        chess::movegen::legalmoves(moves, board);
    }

    bool has_legal_move(const chess::Board& board) {
        profiling::Scope measured(profiling::MOVEGEN);
        return chess::movegen::anylegalmoves(board);
    }

    void generate_captures(chess::Movelist& moves, const chess::Board& board) {
        profiling::Scope measured(profiling::MOVEGEN);
        chess::movegen::legalmoves<chess::movegen::MoveGenType::CAPTURE>(moves, board);
    }

    std::int64_t elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start_).count();
    }

    static bool is_draw(const chess::Board& board, bool null_subtree = false) {
        profiling::Scope measured(profiling::DRAWS);
        // Assume available current-position repetition/50-move claims are taken.
        // The GUI separately handles claim declaration and automatic endings.
        // A hypothetical pass is not game history. Neither it nor its descendants
        // may claim repetition/50-move draws against the actual game's history.
        return insufficient_material(board) ||
               (!null_subtree && (board.isHalfMoveDraw() || board.isRepetition(2)));
    }

    void check_limits(bool between_iterations = false) const {
        if (stop_.load(std::memory_order_relaxed) ||
            (limits_.nodes && result_.nodes >= limits_.nodes) ||
            (limits_.milliseconds && (between_iterations || result_.nodes % 256 == 0) &&
             Clock::now() >= deadline_)) {
            throw Interrupted{};
        }
    }

    void visit(int ply, bool quiescent = false) {
        check_limits();
        ++result_.nodes;  // Includes the root, terminal nodes, and static leaves.
        if (quiescent) ++result_.qnodes;
        result_.selective_depth = std::max(result_.selective_depth, ply);
    }

    static std::optional<int> terminal(const chess::Board& board, bool has_move, int ply,
                                       bool null_subtree = false) {
        if (!has_move) {
            if (!board.inCheck()) return 0;
            return board.sideToMove() == chess::Color::WHITE ? -MATE_SCORE + ply : MATE_SCORE - ply;
        }
        if (is_draw(board, null_subtree)) return 0;
        return std::nullopt;
    }

    static std::optional<int> terminal(const chess::Board& board, const chess::Movelist& moves, int ply,
                                       bool null_subtree = false) {
        return terminal(board, !moves.empty(), ply, null_subtree);
    }

    int quiescence(chess::Board& board, int ply, int qply, int alpha, int beta,
                   PrincipalVariation& pv, bool null_subtree = false) {
        visit(ply, true);
#ifdef CHESSLAB_DIAGNOSTICS
        diagnostics::visit(ply, true, null_subtree);
#endif
        const bool checked = board.inCheck();
        const auto promotion_rank = board.sideToMove() == chess::Color::WHITE ?
                                    0x00FF000000000000ULL : 0x000000000000FF00ULL;
        // Capture-only generation omits quiet promotions. Preserve the complete
        // old sequence for those positions and when ordering is disabled.
        const bool specialized = limits_.fast_movegen && limits_.move_ordering && !checked &&
            !(board.pieces(chess::PieceType::PAWN, board.sideToMove()) & promotion_rank);
        chess::Movelist moves;
        if (!specialized) generate(moves, board);
        if (const auto score = terminal(board, specialized ? has_legal_move(board) : !moves.empty(), ply, null_subtree)) return *score;
        const bool maximizing = board.sideToMove() == chess::Color::WHITE;
        int best;
        if (checked) {
            // Never stand pat in check, including at the soft q-depth limit.
            if (ply >= MAX_SEARCH_PLY) {
                result_.ply_limit_reached = true;
                throw Interrupted{};
            }
            best = maximizing ? -INFINITY_SCORE : INFINITY_SCORE;
        } else {
            best = static_evaluation(board, ply);
            if (qply >= MAX_QUIESCENCE_PLY || ply >= MAX_SEARCH_PLY) {
                ++result_.qcaps;
                return best;
            }
            if (pruning_) {
                if ((maximizing && best >= beta) || (!maximizing && best <= alpha)) { ++result_.beta_cutoffs; return best; }
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
            }
        }
        chess::Movelist tactical;
        if (specialized) generate_captures(tactical, board);
        else for (const auto move : moves) {
                if (checked || board.isCapture(move) || move.typeOf() == chess::Move::PROMOTION) tactical.add(move);
            }
        if (limits_.move_ordering) order_moves(tactical, board, chess::Move{}, chess::Move{}, ordering_, limits_, result_, ply);
        for (const auto move : tactical) {
            PrincipalVariation child_pv;
            int score;
            {
                const auto nnue_delta = nnue_stack_ && limits_.nnue_kernel != "reference" ? nnue_move_delta(board, move) : NnueDelta{};
                ScopedMove played(board, move);
                descend_nnue(board, ply + 1, nnue_delta);
                score = quiescence(board, ply + 1, qply + 1, alpha, beta, child_pv, null_subtree);
            }
            if ((maximizing && score > best) || (!maximizing && score < best)) {
                best = score;
                pv.prepend(move, child_pv);
            }
            if (pruning_) {
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
                if (alpha >= beta) { ++result_.beta_cutoffs; break; }
            }
        }
        return best;
    }

    int minimax(chess::Board& board, int depth, int ply, int alpha, int beta,
                PrincipalVariation& pv, bool follows_previous_pv, std::uint64_t history,
                bool null_subtree = false, int extensions = 0) {
        // A bounded extension budget prevents check chains from postponing the
        // leaf forever. Minimax remains an exhaustive nominal-depth baseline.
        if (pruning_ && limits_.check_extensions && !null_subtree && ply > 0 && depth > 0 &&
            extensions < 2 && ply + depth < MAX_SEARCH_PLY && board.inCheck()) {
            ++depth;
            ++extensions;
            ++result_.check_extensions;
        }
        if (ply >= MAX_SEARCH_PLY) depth = 0;
        if (depth == 0 && limits_.quiescence) return quiescence(board, ply, 0, alpha, beta, pv, null_subtree);
        visit(ply);
#ifdef CHESSLAB_DIAGNOSTICS
        diagnostics::visit(ply, false, null_subtree);
#endif
        if (depth == 0 && limits_.fast_movegen) {
            if (const auto score = terminal(board, has_legal_move(board), ply, null_subtree)) return *score;
            return static_evaluation(board, ply);
        }
        chess::Movelist moves;
        generate(moves, board);
        if (const auto score = terminal(board, moves, ply, null_subtree)) return *score;
        if (depth == 0) return static_evaluation(board, ply);

        const int original_alpha = alpha;
        const int original_beta = beta;
        // Extension budget changes the horizon. Keep its TT contexts separate.
        const auto table_key = board.hash() ^ (limits_.check_extensions && pruning_ ?
            0x9E3779B97F4A7C15ULL * static_cast<std::uint64_t>(extensions + 1) : 0);
        chess::Move table_move{};
        const bool cacheable = table_ && !null_subtree;
        if (cacheable) {
            ++result_.tt_probes;
            const auto* entry = [&] {
                profiling::Scope measured(profiling::TABLE);
                return table_->probe(table_key, history, board.halfMoveClock());
            }();
            // A matching hash never licenses an illegal move.
            if (entry && std::find(moves.begin(), moves.end(), entry->move()) != moves.end()) {
                ++result_.tt_hits;
                table_move = entry->move();
                // Equal depth keeps exact fixed-horizon comparisons meaningful.
                // Other depths remain useful as move-ordering hints only.
                const auto score = table_score(*entry, depth, ply, alpha, beta, pruning_, limits_.quiescence);
                if (score) {
                    ++result_.tt_cutoffs;
                    result_.selective_depth = std::max(result_.selective_depth, ply + entry->length);
                    for (unsigned i = 0; i < entry->length; ++i) pv.emplace_back(entry->pv[i]);
                    return *score;
                }
            }
        }

        // A PV move is meaningful only on its original path, never on a sibling
        // merely at the same ply. result_.pv changes only after a complete pass.
        const auto hint = follows_previous_pv && static_cast<std::size_t>(ply) < result_.pv.size()
                            ? result_.pv[ply] : chess::Move{};
        if (limits_.move_ordering) order_moves(moves, board, hint, table_move, ordering_, limits_, result_, ply);
        const bool maximizing = board.sideToMove() == chess::Color::WHITE;
        const bool selective = pruning_ && !null_subtree && ply > 0 && beta - alpha == 1 &&
            !board.inCheck() && depth <= 3 && game_phase(board) >= 4 &&
            board.halfMoveClock() < 90 && !board.isRepetition(1) &&
            std::abs(alpha) < MATE_THRESHOLD && std::abs(beta) < MATE_THRESHOLD;
        const bool need_static = selective && (limits_.reverse_futility || limits_.futility);
        const int stand = need_static ? static_evaluation(board, ply) : 0;
        if (selective && limits_.reverse_futility && std::abs(stand) < MATE_THRESHOLD &&
            ((maximizing && stand - 120 * depth >= beta) ||
             (!maximizing && stand + 120 * depth <= alpha))) {
            ++result_.reverse_futility_cutoffs;
            return maximizing ? beta : alpha;
        }
        // A unit window is a non-PV scout. Avoid low material/zugzwang risks,
        // near draw/mate bounds, repeated positions, and every nested null path.
        if (pruning_ && limits_.null_move_pruning &&
            null_move_allowed(board, depth, ply, alpha, beta, null_subtree)) {
            const int stand = static_evaluation(board, ply);
            if ((maximizing && stand >= beta) || (!maximizing && stand <= alpha)) {
                ++result_.null_attempts;
                int score;
                PrincipalVariation ignored_pv;
                {
                    ScopedNullMove passed(board);
#ifdef CHESSLAB_DIAGNOSTICS
                    diagnostics::next_null = true;
#endif
                    descend_nnue(board, ply + 1);
                    score = minimax(board, depth - 3, ply + 1,
                                    maximizing ? beta - 1 : alpha,
                                    maximizing ? beta : alpha + 1, ignored_pv, false, 0, true);
                }
                // Never propagate a mate inferred from an artificial pass.
                if (std::abs(score) < MATE_THRESHOLD &&
                    ((maximizing && score >= beta) || (!maximizing && score <= alpha))) {
                    ++result_.null_cutoffs;
                    return maximizing ? beta : alpha;  // Bound only, no null PV/TT entry.
                }
            }
        }
        int best = maximizing ? -INFINITY_SCORE : INFINITY_SCORE;
        bool first = true;
        int move_index = 0;
        chess::Movelist unsuccessful_quiets;
        // Minimax and alpha-beta share the same ordering and first-best tie rule.
        for (const auto move : moves) {
            const bool quiet = !board.isCapture(move) && move.typeOf() != chess::Move::PROMOTION &&
                               move.typeOf() != chess::Move::CASTLING;
            if (!first && selective && limits_.futility && depth <= 2 && quiet &&
                std::abs(best) < MATE_THRESHOLD &&
                move != table_move && move != hint && !ordering_.killer(move, ply) &&
                ordering_.score(board, move) <= 1024 &&
                board.givesCheck(move) == chess::CheckType::NO_CHECK &&
                ((maximizing && stand + 180 * depth <= alpha) ||
                 (!maximizing && stand - 180 * depth >= beta))) {
                ++result_.futility_prunes;
                ++move_index;
                continue;
            }
            PrincipalVariation child_pv;
            const auto parent_key = board.hash();
            const bool reduce = pruning_ && limits_.late_move_reductions && limits_.move_ordering &&
                lmr_candidate(board, move, depth, ply, move_index, alpha, beta, table_move, hint, null_subtree) &&
                !(limits_.killer_heuristic && ordering_.killer(move, ply));
            const int reduction = reduce ? (limits_.adaptive_lmr ?
                adaptive_reduction(depth, move_index, limits_.history_heuristic ? ordering_.score(board, move) : 0,
                                   limits_.lmr_reduction) :
                std::clamp(limits_.lmr_reduction, 1, std::min(3, depth - 2))) : 0;
            int score;
            {
                const auto nnue_delta = nnue_stack_ && limits_.nnue_kernel != "reference" ? nnue_move_delta(board, move) : NnueDelta{};
                ScopedMove played(board, move);
                descend_nnue(board, ply + 1, nnue_delta);
                const auto child_history = cacheable ? next_history(history, parent_key, board) : 0;
                const bool child_follows_pv = follows_previous_pv && move == hint;
                if (reduce) {
                    ++result_.lmr_attempts;
                    ++result_.lmr_searches;
                    score = minimax(board, depth - 1 - reduction, ply + 1, alpha, beta,
                                    child_pv, child_follows_pv, child_history, null_subtree, extensions);
                    if ((maximizing && score > alpha) || (!maximizing && score < beta)) {
                        ++result_.lmr_researches;
                        ++result_.lmr_verifications;
                        child_pv.clear();
                        // Verify at nominal depth using this scout's window.
                        // An enclosing PVS node handles any wider PV re-search.
                        score = minimax(board, depth - 1, ply + 1, alpha, beta,
                                        child_pv, child_follows_pv, child_history, null_subtree, extensions);
                    }
                } else if (pruning_ && limits_.principal_variation_search && !first && beta - alpha > 1) {
                    ++result_.pvs_scouts;
                    const int scout_alpha = maximizing ? alpha : beta - 1;
                    const int scout_beta = maximizing ? alpha + 1 : beta;
                    score = minimax(board, depth - 1, ply + 1, scout_alpha, scout_beta,
                                    child_pv, child_follows_pv, child_history, null_subtree, extensions);
                    if (score > alpha && score < beta) {
                        ++result_.pvs_researches;
                        child_pv.clear();
                        score = minimax(board, depth - 1, ply + 1, alpha, beta,
                                        child_pv, child_follows_pv, child_history, null_subtree, extensions);
                    }
                } else {
                    score = minimax(board, depth - 1, ply + 1, alpha, beta,
                                    child_pv, child_follows_pv, child_history, null_subtree, extensions);
                }
            }
            first = false;
            ++move_index;
            if ((maximizing && score > best) || (!maximizing && score < best)) {
                best = score;
                pv.prepend(move, child_pv);
            }
            if (pruning_) {
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
                if (alpha >= beta) {
                    ++result_.beta_cutoffs;
                    if (quiet && limits_.move_ordering && !null_subtree) {
                        if (limits_.killer_heuristic && ordering_.killer(move, ply)) ++result_.killer_cutoffs;
                        if (limits_.history_heuristic) ++result_.history_updates;
                        ordering_.cutoff(board, move, ply, depth, unsuccessful_quiets,
                                         limits_.history_heuristic, limits_.killer_heuristic);
                    }
                    break;
                }
            }
            if (quiet) unsuccessful_quiets.add(move);
        }
        if (cacheable) {
            const auto bound = best <= original_alpha ? Bound::UPPER :
                               best >= original_beta ? Bound::LOWER : Bound::EXACT;
            // Interrupted nodes throw before reaching this store. Completed
            // descendants remain valid, even when their parent pass is stopped.
            profiling::Scope measured(profiling::TABLE);
            table_->store(table_key, history, board.halfMoveClock(), depth,
                          score_to_table(best, ply), bound, pv, ply);
        }
        return best;
    }
};

}  // namespace

SearchResult search(chess::Board board, const SearchLimits& limits,
                    bool alpha_beta, const std::atomic<bool>& stop,
                    const SearchProgress& progress) {
    return Search(limits, alpha_beta, stop).run(board, progress);
}

std::uint64_t perft(chess::Board& board, int depth) {
    if (depth == 0) return 1;
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    if (depth == 1) return moves.size();
    std::uint64_t nodes = 0;
    for (const auto move : moves) {
        board.makeMove<true>(move);
        nodes += perft(board, depth - 1);
        board.unmakeMove(move);
    }
    return nodes;
}

}  // namespace chesslab
