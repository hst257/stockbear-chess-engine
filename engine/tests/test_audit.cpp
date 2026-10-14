#include "search.hpp"
#include "scoped_move.hpp"

#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

int main() {
    try {
        std::mt19937 random(20261015);
        const char* positions[] = {chess::constants::STARTPOS,
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
            "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
            "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1"};
        unsigned verified = 0;
        for (const auto fen : positions) {
            for (int walk = 0; walk < 40; ++walk) {
                chess::Board board(fen), original = board;
                std::vector<chess::Move> played;
                for (int ply = 0; ply < 120; ++ply) {
                    chess::Movelist moves;
                    chess::movegen::legalmoves(moves, board);
                    if (moves.empty()) break;
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
        std::cout << "Verified " << verified << " random make/unmake transitions including complete history\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
