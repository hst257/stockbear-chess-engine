#include "search.hpp"
#include "scoped_move.hpp"

#include <algorithm>
#include <memory>

namespace chesslab {
namespace {

constexpr int INFINITY_SCORE = 32000;
constexpr int MAX_QUIESCENCE_PLY = 16;
struct Interrupted {};

void order_moves(chess::Movelist& moves, const chess::Board& board,
                 chess::Move pv_move, chess::Move table_move) {
    for (auto& move : moves) {
        int priority = 0;
        int capture_bonus = 0;
        if (board.isCapture(move)) {
            // MVV-LVA: most valuable victim, least valuable attacker. The rules
            // library handles en passant's empty destination and castling.
            capture_bonus = 10 * PIECE_VALUES[board.getCapturing<chess::PieceType>(move)] -
                            PIECE_VALUES[board.at<chess::PieceType>(move.from())];
            priority = 10000 + capture_bonus;
        }
        if (move.typeOf() == chess::Move::PROMOTION) {
            priority = 20000 + PIECE_VALUES[move.promotionType()] + capture_bonus;
        }
        if (move == pv_move) priority = 32000;
        if (move == table_move) priority = 32500;
        move.setScore(static_cast<std::int16_t>(priority));
    }
    // Equal priorities preserve the library order, including quiet moves.
    std::stable_sort(moves.begin(), moves.end(), [](const auto a, const auto b) {
        return a.score() > b.score();
    });
}

class Search {
public:
    Search(const SearchLimits& limits, bool pruning, const std::atomic<bool>& stop)
        : limits_(limits), pruning_(pruning), stop_(stop), start_(Clock::now()),
          deadline_(limits.milliseconds ? start_ + std::chrono::milliseconds(limits.milliseconds) : Clock::time_point::max()),
          table_(limits.transposition_table ? std::make_unique<TranspositionTable>(limits.hash_megabytes) : nullptr) {}

    SearchResult run(chess::Board& board, const SearchProgress& progress) {
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        // If stopped before depth one finishes, still return a legal move.
        if (!moves.empty() && !is_draw(board)) result_.best_move = moves[0];
        const bool terminal = moves.empty() || is_draw(board);
        const int first = (limits_.iterative_deepening && !terminal) || (limits_.time_managed && terminal) ? 1 : limits_.depth;
        for (int depth = first; depth <= limits_.depth; ++depth) {
            // Only commit a complete pass. Recursive PV updates stay local, so an
            // interrupted deeper pass cannot corrupt the saved move or score.
            std::vector<chess::Move> pv;
            int score;
            try {
                check_limits(true);
                score = minimax(board, depth, 0, -INFINITY_SCORE, INFINITY_SCORE, pv, true, limits_.history);
            } catch (const Interrupted&) {
                break;
            }
            result_.white_score = score;
            result_.pv = std::move(pv);
            result_.depth = depth;
            result_.complete = depth == limits_.depth;
            if (!result_.pv.empty()) result_.best_move = result_.pv.front();
            result_.milliseconds = elapsed();
            result_.hashfull = table_ ? table_->hashfull() : 0;
            if (progress) progress(result_);
            // Only time-managed searches stop on a proven root mate. Explicit
            // depth requests retain their reproducible target-depth behavior.
            if (limits_.time_managed && (terminal || std::abs(score) >= MATE_THRESHOLD)) break;
        }
        // Totals include unfinished work; depth/PV/score refer to the saved pass.
        result_.milliseconds = elapsed();
        result_.hashfull = table_ ? table_->hashfull() : 0;
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

    std::int64_t elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start_).count();
    }

    static bool is_draw(const chess::Board& board) {
        // Assume available current-position repetition/50-move claims are taken.
        // The GUI separately handles claim declaration and automatic endings.
        return board.isInsufficientMaterial() || board.isHalfMoveDraw() || board.isRepetition(2);
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

    static std::optional<int> terminal(const chess::Board& board, const chess::Movelist& moves, int ply) {
        if (moves.empty()) {
            if (!board.inCheck()) return 0;
            return board.sideToMove() == chess::Color::WHITE ? -MATE_SCORE + ply : MATE_SCORE - ply;
        }
        if (is_draw(board)) return 0;
        return std::nullopt;
    }

    int quiescence(chess::Board& board, int ply, int qply, int alpha, int beta,
                   std::vector<chess::Move>& pv) {
        visit(ply, true);
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        if (const auto score = terminal(board, moves, ply)) return *score;
        const bool checked = board.inCheck();
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
            best = evaluate(board, limits_.use_pst);
            if (qply >= MAX_QUIESCENCE_PLY || ply >= MAX_SEARCH_PLY) {
                ++result_.qcaps;
                return best;
            }
            if (pruning_) {
                if ((maximizing && best >= beta) || (!maximizing && best <= alpha)) return best;
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
            }
        }
        chess::Movelist tactical;
        for (const auto move : moves) {
            if (checked || board.isCapture(move) || move.typeOf() == chess::Move::PROMOTION) tactical.add(move);
        }
        if (limits_.move_ordering) order_moves(tactical, board, chess::Move{}, chess::Move{});
        for (const auto move : tactical) {
            std::vector<chess::Move> child_pv;
            int score;
            {
                ScopedMove played(board, move);
                score = quiescence(board, ply + 1, qply + 1, alpha, beta, child_pv);
            }
            if ((maximizing && score > best) || (!maximizing && score < best)) {
                best = score;
                pv.assign(1, move);
                pv.insert(pv.end(), child_pv.begin(), child_pv.end());
            }
            if (pruning_) {
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
                if (alpha >= beta) break;
            }
        }
        return best;
    }

    int minimax(chess::Board& board, int depth, int ply, int alpha, int beta,
                std::vector<chess::Move>& pv, bool follows_previous_pv, std::uint64_t history) {
        if (depth == 0 && limits_.quiescence) return quiescence(board, ply, 0, alpha, beta, pv);
        visit(ply);
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        if (const auto score = terminal(board, moves, ply)) return *score;
        if (depth == 0) return evaluate(board, limits_.use_pst);

        const int original_alpha = alpha;
        const int original_beta = beta;
        chess::Move table_move{};
        if (table_) {
            ++result_.tt_probes;
            const auto* entry = table_->probe(board.hash(), history, board.halfMoveClock());
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
        if (limits_.move_ordering) order_moves(moves, board, hint, table_move);
        const bool maximizing = board.sideToMove() == chess::Color::WHITE;
        int best = maximizing ? -INFINITY_SCORE : INFINITY_SCORE;
        bool first = true;
        // Minimax and alpha-beta share the same ordering and first-best tie rule.
        for (const auto move : moves) {
            std::vector<chess::Move> child_pv;
            const auto parent_key = board.hash();
            int score;
            {
                ScopedMove played(board, move);
                const auto child_history = table_ ? next_history(history, parent_key, board) : 0;
                const bool child_follows_pv = follows_previous_pv && move == hint;
                if (pruning_ && limits_.principal_variation_search && !first && beta - alpha > 1) {
                    ++result_.pvs_scouts;
                    const int scout_alpha = maximizing ? alpha : beta - 1;
                    const int scout_beta = maximizing ? alpha + 1 : beta;
                    score = minimax(board, depth - 1, ply + 1, scout_alpha, scout_beta,
                                    child_pv, child_follows_pv, child_history);
                    if (score > alpha && score < beta) {
                        ++result_.pvs_researches;
                        child_pv.clear();
                        score = minimax(board, depth - 1, ply + 1, alpha, beta,
                                        child_pv, child_follows_pv, child_history);
                    }
                } else {
                    score = minimax(board, depth - 1, ply + 1, alpha, beta,
                                    child_pv, child_follows_pv, child_history);
                }
            }
            first = false;
            if ((maximizing && score > best) || (!maximizing && score < best)) {
                best = score;
                pv.assign(1, move);
                pv.insert(pv.end(), child_pv.begin(), child_pv.end());
            }
            if (pruning_) {
                if (maximizing) alpha = std::max(alpha, best);
                else beta = std::min(beta, best);
                if (alpha >= beta) break;
            }
        }
        if (table_) {
            const auto bound = best <= original_alpha ? Bound::UPPER :
                               best >= original_beta ? Bound::LOWER : Bound::EXACT;
            // Interrupted nodes throw before reaching this store. Completed
            // descendants remain valid, even when their parent pass is stopped.
            table_->store(board.hash(), history, board.halfMoveClock(), depth,
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
