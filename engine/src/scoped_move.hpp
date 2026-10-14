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

// The pinned rules library already implements reversible side/EP/Zobrist updates.
// This search-only pass preserves pieces, castling rights and the real halfmove clock.
class ScopedNullMove {
public:
    explicit ScopedNullMove(chess::Board& board) : board_(board) { board_.makeNullMove(); }
    ~ScopedNullMove() { board_.unmakeNullMove(); }
    ScopedNullMove(const ScopedNullMove&) = delete;
    ScopedNullMove& operator=(const ScopedNullMove&) = delete;

private:
    chess::Board& board_;
};

}  // namespace chesslab
