#pragma once

#include "chess.hpp"
#include "profiling.hpp"

namespace chesslab {

// Restore every speculative move, including when stop/deadline unwinds recursion.
class ScopedMove {
public:
    ScopedMove(chess::Board& board, chess::Move move) : board_(board), move_(move) {
        profiling::Scope measured(profiling::MAKE);
        board_.makeMove<true>(move_);
    }
    ~ScopedMove() { profiling::Scope measured(profiling::UNMAKE); board_.unmakeMove(move_); }
    ScopedMove(const ScopedMove&) = delete;
    ScopedMove& operator=(const ScopedMove&) = delete;

private:
    chess::Board& board_;
    chess::Move move_;
};

// The pinned rules library already implements reversible side/EP/Zobrist updates.
// This search-only pass preserves pieces, castling rights and the real halfmove clock.
class ScopedNullMove {
public:
    explicit ScopedNullMove(chess::Board& board) : board_(board) {
        profiling::Scope measured(profiling::MAKE); board_.makeNullMove();
    }
    ~ScopedNullMove() { profiling::Scope measured(profiling::UNMAKE); board_.unmakeNullMove(); }
    ScopedNullMove(const ScopedNullMove&) = delete;
    ScopedNullMove& operator=(const ScopedNullMove&) = delete;

private:
    chess::Board& board_;
};

}  // namespace chesslab
