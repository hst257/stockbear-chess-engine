#include "search.hpp"
#include "scoped_move.hpp"
#include "pawn_cache.hpp"
#include "strength.hpp"

#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main() {
    try {
        chesslab::OrderingHistory ordering;
        const chess::Board start;
        const auto quiet = chess::uci::uciToMove(start, "g1f3");
        for (int i = 0; i < 10000; ++i) ordering.update(start, quiet, 2048);
        require(ordering.score(start, quiet) <= 8192, "History overflowed positive bound");
        for (int i = 0; i < 10000; ++i) ordering.update(start, quiet, -2048);
        require(ordering.score(start, quiet) >= -8192, "History overflowed negative bound");
        require(chesslab::adaptive_reduction(6, 16, -2000, 1) >
                chesslab::adaptive_reduction(6, 4, 2000, 1), "Adaptive LMR ignores move/history signals");
        require(chesslab::adaptive_reduction(3, 30, -8192, 3) == 1, "LMR reduced through static horizon");
        std::mt19937 random(20261015);
        const char* positions[] = {chess::constants::STARTPOS,
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
            "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1"};
        unsigned verified = 0;
        chesslab::PawnCache pawn_cache;
        for (const auto fen : positions) {
            for (int walk = 0; walk < 40; ++walk) {
                chess::Board board(fen), original = board;
                std::vector<chess::Move> played;
                for (int ply = 0; ply < 120; ++ply) {
                    chess::Movelist moves;
                    chess::movegen::legalmoves(moves, board);
                    if (moves.empty()) break;
                    for (bool pst : {false, true}) {
                        chesslab::EvaluationOptions options;
                        options.enabled[(walk + ply) % options.enabled.size()] = false;
                        const int uncached = chesslab::evaluate(board, pst, options);
                        const int cached = chesslab::evaluate(board, pst, options, &pawn_cache);
                        require(cached == uncached, "Pawn cache changed evaluation with live occupancy/options");
                    }
                    const auto before = board;
                    const auto move = moves[random() % moves.size()];
                    {
                        chesslab::ScopedMove guard(board, move);
                        require(board.hash() == board.zobrist(), "Incremental hash differs from recomputation");
                    }
                    require(board.fullyEquals(before), "RAII move failed to restore board/history");
                    if (!board.inCheck()) {
                        { chesslab::ScopedNullMove guard(board);
                          require(board.hash() == board.zobrist(), "Null hash mismatch"); }
                        require(board.fullyEquals(before), "Null move failed to restore full history/state");
                    }
                    board.makeMove<true>(move);
                    played.push_back(move);
                    ++verified;
                }
                while (!played.empty()) { board.unmakeMove(played.back()); played.pop_back(); }
                require(board.fullyEquals(original), "Random walk failed to restore original state/history");
            }
        }
        require(pawn_cache.hits > 0 && pawn_cache.hits < pawn_cache.probes, "Pawn hit/miss paths not exercised");
        // More distinct legal-rank pawn pairs than slots force index collisions.
        chesslab::PawnCache collisions;
        for (int white = 8; white < 56; ++white) {
            for (int black = 8; black < 56; ++black) {
                if (white == black) continue;
                const auto w = chess::Bitboard::fromSquare(white), b = chess::Bitboard::fromSquare(black);
                const auto& entry = collisions.get(w, b);
                require(entry.pawns[0] == w && entry.pawns[1] == b, "Pawn cache reused a colliding index without full keys");
            }
        }
        std::atomic<bool> stopped{false};
        for (const auto fen : positions) {
            chesslab::SearchLimits limits;
            limits.depth = 4;
            limits.nodes = 20000;
            const auto fast = chesslab::search(chess::Board(fen), limits, true, stopped);
            limits.fast_movegen = false;
            const auto full = chesslab::search(chess::Board(fen), limits, true, stopped);
            require(fast.nodes == full.nodes && fast.white_score == full.white_score &&
                    fast.depth == full.depth && fast.pv == full.pv, "Bounded search changed with fast generation");
        }
        std::cout << "Verified " << verified << " random make/unmake transitions including complete history\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
