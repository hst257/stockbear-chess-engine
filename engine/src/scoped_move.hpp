#pragma once

#include "chess.hpp"

namespace chesslab {

// Restore every speculative move, including when stop/deadline unwinds recursion.
class ScopedMove {
public:
    ScopedMove(chess::Board& board, chess::Move move) : board_(board), move_(move) {
        board_.makeMove<true>(move_);
    }
    ~ScopedMove() { board_.unmakeMove(move_); }
    ScopedMove(const ScopedMove&) = delete;
    ScopedMove& operator=(const ScopedMove&) = delete;

private:
    chess::Board& board_;
    chess::Move move_;
};

}  // namespace chesslab
