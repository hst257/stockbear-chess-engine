#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <vector>

#include "chess.hpp"

namespace chesslab {

constexpr int MATE_SCORE = 30000;

struct SearchLimits {
    int depth = 3;
    std::uint64_t nodes = 0;  // Zero means no node limit.
    int milliseconds = 0;    // Zero means no time limit.
    bool iterative_deepening = true;
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
};

int evaluate_material(const chess::Board& board);
using SearchProgress = std::function<void(const SearchResult&)>;
SearchResult search(chess::Board board, const SearchLimits& limits,
                    bool alpha_beta, const std::atomic<bool>& stop,
                    const SearchProgress& progress = {});
std::uint64_t perft(chess::Board& board, int depth);

}  // namespace chesslab
