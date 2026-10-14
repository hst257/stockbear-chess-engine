#include "search.hpp"

#include <algorithm>
#include <limits>

namespace chesslab {
namespace {

constexpr int INFINITY_SCORE = 32000;
struct Interrupted {};

class Search {
public:
    Search(const SearchLimits& limits, bool pruning, const std::atomic<bool>& stop)
        : limits_(limits), pruning_(pruning), stop_(stop), start_(Clock::now()) {}

    SearchResult run(chess::Board& board, const SearchProgress& progress) {
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        // If stopped before depth one finishes, still return a legal move.
        if (!moves.empty() && !is_draw(board)) result_.best_move = moves[0];
        const bool terminal = moves.empty() || is_draw(board);
        const int first = limits_.iterative_deepening && !terminal ? 1 : limits_.depth;
        for (int depth = first; depth <= limits_.depth; ++depth) {
            // Only commit a complete pass. Recursive PV updates stay local, so an
            // interrupted deeper pass cannot corrupt the saved move or score.
            std::vector<chess::Move> pv;
            int score;
            try {
                score = minimax(board, depth, 0, -INFINITY_SCORE, INFINITY_SCORE, pv);
            } catch (const Interrupted&) {
                break;
            }
            result_.white_score = score;
            result_.pv = std::move(pv);
            result_.depth = depth;
            result_.complete = depth == limits_.depth;
            if (!result_.pv.empty()) result_.best_move = result_.pv.front();
            result_.milliseconds = elapsed();
            if (progress) progress(result_);
        }
        // Totals include unfinished work; depth/PV/score refer to the saved pass.
        result_.milliseconds = elapsed();
        return result_;
    }

private:
    using Clock = std::chrono::steady_clock;
    const SearchLimits& limits_;
    bool pruning_;
    const std::atomic<bool>& stop_;
    Clock::time_point start_;
    SearchResult result_;

    std::int64_t elapsed() const {
        return std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - start_).count();
    }

    static bool is_draw(const chess::Board& board) {
        // Assume available current-position repetition/50-move claims are taken.
        // The GUI separately handles claim declaration and automatic endings.
        return board.isInsufficientMaterial() || board.isHalfMoveDraw() || board.isRepetition(2);
    }

    int minimax(chess::Board& board, int depth, int ply, int alpha, int beta,
                std::vector<chess::Move>& pv) {
        if (stop_.load(std::memory_order_relaxed) ||
            (limits_.nodes && result_.nodes >= limits_.nodes) ||
            (limits_.milliseconds && (result_.nodes % 1024 == 0) &&
             Clock::now() - start_ >= std::chrono::milliseconds(limits_.milliseconds))) {
            throw Interrupted{};
        }
        ++result_.nodes;  // Includes the root, terminal nodes, and static leaves.
        result_.selective_depth = std::max(result_.selective_depth, ply);
        chess::Movelist moves;
        chess::movegen::legalmoves(moves, board);
        if (moves.empty()) {
            if (!board.inCheck()) return 0;
            return board.sideToMove() == chess::Color::WHITE ? -MATE_SCORE + ply : MATE_SCORE - ply;
        }
        if (is_draw(board)) return 0;
        if (depth == 0) return evaluate_material(board);

        const bool maximizing = board.sideToMove() == chess::Color::WHITE;
        int best = maximizing ? -INFINITY_SCORE : INFINITY_SCORE;
        // Both modes traverse the exact same library-generated move order.
        // There is no capture sorting, transposition table, or other heuristic.
        for (const auto move : moves) {
            std::vector<chess::Move> child_pv;
            board.makeMove<true>(move);
            const int score = minimax(board, depth - 1, ply + 1, alpha, beta, child_pv);
            board.unmakeMove(move);
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
};

}  // namespace

int evaluate_material(const chess::Board& board) {
    constexpr int values[] = {100, 320, 330, 500, 900, 0};
    int score = 0;
    for (int kind = 0; kind < 6; ++kind) {
        const auto type = chess::PieceType(static_cast<chess::PieceType::underlying>(kind));
        score += values[kind] * (board.pieces(type, chess::Color::WHITE).count() -
                                board.pieces(type, chess::Color::BLACK).count());
    }
    return score;
}

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
