#include "search.hpp"

#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

chess::Move legal_move(const chess::Board& board, const std::string& text) {
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    for (auto move : moves) if (chess::uci::moveToUci(move) == text) return move;
    throw std::runtime_error("Illegal test move: " + text);
}

void hash_sequence(const std::string& fen, const std::vector<std::string>& sequence) {
    chess::Board board(fen);
    const auto original = board;
    std::vector<chess::Move> moves;
    for (const auto& text : sequence) {
        const auto move = legal_move(board, text);
        moves.push_back(move);
        board.makeMove<true>(move);
        require(board.hash() == board.zobrist(), "Incremental hash differs from full recomputation");
    }
    for (auto it = moves.rbegin(); it != moves.rend(); ++it) {
        board.unmakeMove(*it);
        require(board.hash() == board.zobrist(), "Unmake did not restore hash");
    }
    require(board.fullyEquals(original), "Unmake did not restore full state and repetition history");
}

void hashes() {
    hash_sequence(chess::constants::STARTPOS, {"e2e4", "a7a6", "e4e5", "d7d5", "e5d6"});
    hash_sequence("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", {"e1g1", "e8c8"});
    hash_sequence("1r5k/P7/8/8/8/8/8/7K w - - 0 1", {"a7b8n"});
    hash_sequence("7k/8/8/8/8/8/p7/1R5K b - - 0 1", {"a2b1q"});
    hash_sequence("7k/P7/8/8/8/8/8/7K w - - 0 1", {"a7a8q"});
    const chess::Board ep("7k/8/8/3pP3/8/8/8/7K w - d6 0 2");
    const chess::Board no_ep("7k/8/8/3pP3/8/8/8/7K w - - 0 2");
    require(ep.hash() != no_ep.hash(), "Legal en passant missing from Zobrist key");
    const chess::Board castle("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
    const chess::Board no_castle("r3k2r/8/8/8/8/8/8/R3K2R w - - 0 1");
    require(castle.hash() != no_castle.hash(), "Castling rights missing from key");
    const chess::Board black("r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1");
    require(castle.hash() != black.hash(), "Side to move missing from key");
    const chess::Board clock("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 99 50");
    require(castle.hash() == clock.hash(), "Board Zobrist unexpectedly includes move counters");
}

void bounds() {
    chesslab::TableEntry entry;
    entry.depth = 4;
    entry.score = 20;
    for (bool pruning : {false, true}) {
        entry.bound = chesslab::Bound::EXACT;
        require(chesslab::table_score(entry, 4, 0, 0, 10, pruning) == 20, "Exact score not reusable");
        require(!chesslab::table_score(entry, 3, 0, 0, 10, pruning), "Different horizon reused");
        require(!chesslab::table_score(entry, 5, 0, 0, 10, pruning), "Shallow score reused");
        entry.bound = chesslab::Bound::LOWER;
        require(bool(chesslab::table_score(entry, 4, 0, 0, 20, pruning)) == pruning, "Lower bound cutoff incorrect");
        require(!chesslab::table_score(entry, 4, 0, 0, 21, pruning), "Lower bound treated as exact");
        entry.bound = chesslab::Bound::UPPER;
        require(bool(chesslab::table_score(entry, 4, 0, 20, 30, pruning)) == pruning, "Upper bound cutoff incorrect");
        require(!chesslab::table_score(entry, 4, 0, 19, 30, pruning), "Upper bound treated as exact");
    }
    for (int score : {0, 50, -700, 29995, -29995}) {
        for (int ply : {0, 1, 15, 64}) {
            require(chesslab::score_from_table(chesslab::score_to_table(score, ply), ply) == score,
                    "Mate score normalization failed round trip");
        }
    }
    require(chesslab::score_from_table(chesslab::score_to_table(29995, 3), 1) == 29997,
            "Winning mate distance not adjusted across plies");
    require(chesslab::score_from_table(chesslab::score_to_table(-29995, 3), 1) == -29997,
            "Losing mate distance not adjusted across plies");
    entry.bound = chesslab::Bound::EXACT;
    entry.search_ply = 2;
    require(chesslab::table_score(entry, 4, 2, 0, 30, true, true) == 20,
            "Matching quiescence allowance rejected");
    require(!chesslab::table_score(entry, 4, 3, 0, 30, true, true),
            "Different absolute quiescence allowance reused");
}

void storage() {
    chesslab::TranspositionTable table(1);
    const std::vector<chess::Move> pv{chess::Move::make(chess::Square("e2"), chess::Square("e4"))};
    require(table.probe(0, 0, 0) == nullptr, "Uninitialized zero key matched");
    table.store(0, 0, 0, 3, 100, chesslab::Bound::EXACT, pv);
    require(table.probe(0, 0, 0)->move() == pv[0], "Move lost in compact PV encoding");
    require(!table.probe(0, 1, 0) && !table.probe(0, 0, 1), "Draw context not verified");
    table.store(0, 0, 0, 2, 200, chesslab::Bound::EXACT, pv);
    require(table.probe(0, 0, 0)->score == 100, "Shallow entry replaced deeper entry");
    table.store(0, 0, 0, 3, 200, chesslab::Bound::LOWER, pv);
    require(table.probe(0, 0, 0)->bound == chesslab::Bound::EXACT, "Bound replaced same-depth exact entry");
    table.store(0, 0, 0, 4, 300, chesslab::Bound::UPPER, pv);
    require(table.probe(0, 0, 0)->depth == 4 && table.probe(0, 0, 0)->score == 300,
            "Deeper replacement not stored");
    bool collision = false;
    for (std::uint64_t key = 1; key < table.size() * 32; ++key) {
        table.store(key, 0, 0, 4, 42, chesslab::Bound::EXACT, pv);
        if (!table.probe(0, 0, 0)) {
            require(table.probe(key, 0, 0) != nullptr, "Collision key not stored");
            collision = true;
            break;
        }
    }
    require(collision, "Collision test did not exercise replacement");
    require(table.hashfull() >= 0 && table.hashfull() <= 1000, "Invalid hash occupancy");
    require(table.size() * sizeof(chesslab::TableEntry) <= 1024 * 1024, "Hash memory cap exceeded");
}

std::uint64_t play(chess::Board& board, const std::vector<std::string>& moves) {
    std::uint64_t history = 0;
    for (const auto& text : moves) {
        const auto key = board.hash();
        board.makeMove<true>(legal_move(board, text));
        history = chesslab::next_history(history, key, board);
    }
    return history;
}

void histories() {
    chess::Board first, second;
    const auto a = play(first, {"g1f3", "g8f6", "b1c3", "b8c6"});
    const auto b = play(second, {"b1c3", "b8c6", "g1f3", "g8f6"});
    require(first.hash() == second.hash() && first.halfMoveClock() == second.halfMoveClock(),
            "History test positions differ");
    require(a != b, "Different reversible histories not distinguished");
    chesslab::TranspositionTable table(1);
    const std::vector<chess::Move> pv{legal_move(first, "e2e4")};
    table.store(first.hash(), a, first.halfMoveClock(), 3, 100, chesslab::Bound::EXACT, pv);
    require(!table.probe(second.hash(), b, second.halfMoveClock()), "History-dependent score reused");
    const auto parent = first.hash();
    first.makeMove<true>(pv[0]);
    require(chesslab::next_history(a, parent, first) == 0, "Pawn move did not reset history");
    chess::Board capture("7k/8/8/8/8/8/q7/R6K w - - 12 10");
    const auto parent_capture = capture.hash();
    capture.makeMove<true>(legal_move(capture, "a1a2"));
    require(chesslab::next_history(a, parent_capture, capture) == 0, "Capture did not reset history");
}

chesslab::SearchResult qsearch(const std::string& fen, bool pruning, std::uint64_t nodes = 0) {
    chesslab::SearchLimits limits;
    limits.depth = 0;  // Exercise quiescence directly; public UCI still requires depth >= 1.
    limits.iterative_deepening = false;
    limits.transposition_table = false;
    limits.use_pst = false;
    limits.nodes = nodes;
    std::atomic<bool> stop{false};
    return chesslab::search(chess::Board(fen), limits, pruning, stop);
}

void quiescence() {
    for (bool pruning : {false, true}) {
        auto black = qsearch("7k/8/8/1p6/Q7/8/8/7K b - - 0 1", pruning);
        require(black.complete && black.white_score == -100, "Black recapture not resolved");
        require(chess::uci::moveToUci(black.pv.front()) == "b5a4", "Black tactical PV missing");
        auto white = qsearch("7k/8/8/q7/1P6/8/8/7K w - - 0 1", pruning);
        require(white.complete && white.white_score == 100, "White capture not resolved");
        auto ep = qsearch("7k/8/8/3pP3/8/8/8/7K w - d6 0 2", pruning);
        require(ep.white_score == 100 && ep.pv.front().typeOf() == chess::Move::ENPASSANT,
                "Quiescence omitted en passant");
        auto promotion = qsearch("7k/P7/8/8/8/8/8/7K w - - 0 1", pruning);
        require(promotion.white_score == 900 && promotion.pv.front().typeOf() == chess::Move::PROMOTION,
                "Quiet promotion omitted");
        const std::string checked = "7k/8/8/8/8/8/7R/7K b - - 0 1";
        auto evasions = qsearch(checked, pruning);
        require(!evasions.pv.empty() && evasions.qnodes > 1, "Stand pat accepted while in check");
        chess::Board board(checked);
        require(!board.isCapture(evasions.pv.front()), "Quiet check evasion not exercised");
        for (const auto move : evasions.pv) {
            require(legal_move(board, chess::uci::moveToUci(move)) == move, "Illegal quiescence PV");
            board.makeMove<true>(move);
        }
        require(!board.inCheck(), "Quiescence finished on unresolved check");
        require(qsearch("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", pruning).white_score == 30000,
                "Quiescence checkmate score incorrect");
        require(qsearch("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", pruning).white_score == 0,
                "Quiescence stalemate score incorrect");
        require(qsearch("7k/8/8/8/3N4/8/8/7K w - - 0 1", pruning).white_score == 0,
                "Quiescence ignored insufficient material");
        auto stopped = qsearch("7k/P7/8/8/8/8/8/7K w - - 0 1", pruning, 1);
        require(!stopped.complete && stopped.nodes == 1 && stopped.qnodes == 1 && stopped.pv.empty(),
                "Quiescence node budget did not interrupt without publishing partial PV");
    }
}

void pvs() {
    chesslab::SearchLimits limits;
    limits.depth = 3;
    limits.transposition_table = false;
    limits.iterative_deepening = false;
    limits.move_ordering = false;  // Force probes that need a full-window re-search.
    std::atomic<bool> stop{false};
    limits.principal_variation_search = false;
    auto full = chesslab::search(chess::Board(), limits, true, stop);
    limits.principal_variation_search = true;
    auto scouted = chesslab::search(chess::Board(), limits, true, stop);
    require(full.complete && scouted.complete && full.white_score == scouted.white_score,
            "PVS changed full-window score");
    require(scouted.pvs_scouts > 0 && scouted.pvs_researches > 0, "PVS re-search path not exercised");
    limits.depth = 2;
    auto minimax = chesslab::search(chess::Board(), limits, false, stop);
    require(minimax.complete && minimax.pvs_scouts == 0 && minimax.pvs_researches == 0,
            "PVS activated without alpha-beta");
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string test = argc == 2 ? argv[1] : "";
        if (test == "hashes") hashes();
        else if (test == "bounds") bounds();
        else if (test == "storage") storage();
        else if (test == "histories") histories();
        else if (test == "quiescence") quiescence();
        else if (test == "pvs") pvs();
        else throw std::runtime_error("Expected hashes, bounds, storage, histories, quiescence, or pvs");
        std::cout << test << " passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
