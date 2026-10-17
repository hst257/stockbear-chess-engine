// Development-only actual compact search updater: deterministic varied edges.
#include "nnue.hpp"
#include "small_sort.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <vector>
using namespace chesslab;
struct Edge {
    chess::Board before, after;
    chess::Move move;
    NnueAccumulator parent;
    NnueDelta delta;
    union {
        NnueSearchFeatures states;
        // Equal corpus stride/cache footprint for strategy 2/4/5. Only the
        // active states member is used; compact return/copy costs remain real.
        std::array<std::uint8_t, sizeof(NnueFeatures)> state_storage;
    };
    std::string kind;
    bool null_edge;
    int rows;
};
std::vector<Edge> edges;
std::uint64_t digest = 1469598103934665603ULL;
volatile std::uint64_t sink = 0;
void hash(const void* data, unsigned n) {
    const auto* bytes = static_cast<const unsigned char*>(data);
    for (unsigned i = 0; i < n; ++i) digest = (digest ^ bytes[i]) * 1099511628211ULL;
}
void check(const chess::Board& b, const NnueAccumulator& a, const NnueAccumulator& expected) {
    for (int p = 0; p < 2; ++p) {
        if (std::memcmp(a.values[p].data(), expected.values[p].data(), NNUE_WIDTH * sizeof(float)))
            throw std::runtime_error("Accumulator lane parity");
        hash(a.values[p].data(), NNUE_WIDTH * sizeof(float));
    }
    const float x = nnue_side_to_move(b, a), y = nnue_side_to_move(b, expected);
    if (std::memcmp(&x, &y, 4) || nnue_white_score(b, a) != nnue_white_score(b, expected))
        throw std::runtime_error("Head / CP parity");
    hash(&x, 4);
}
void prepare() {
    std::mt19937 sort_rng(20261017);
    for (int n = 0; n <= 16; ++n) for (int trial = 0; trial < 1000; ++trial) {
        int actual[16], expected[16];
        for (int i=0;i<n;++i) actual[i]=(i+1)*(i%2 ? -1 : 1);
        std::shuffle(actual,actual+n,sort_rng); std::copy_n(actual,n,expected);
        stage2::small_sort(actual,n,[](int f){return std::abs(f);});
        std::sort(expected,expected+n,[](int a,int b){return std::abs(a)<std::abs(b);});
        if (!std::equal(actual,actual+n,expected)) throw std::runtime_error("Small sort ordering");
    }
    const char* fens[] = {chess::constants::STARTPOS,
        "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
        "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
        "r6k/1P6/8/8/8/8/8/K7 w - - 0 1",
        "7k/4P3/8/8/8/8/5p2/K7 w - - 0 1",
        "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7"};
    std::mt19937 rng(20261017);
    for (auto fen : fens) for (int walk = 0; walk < 8; ++walk) {
        chess::Board board(fen);
        NnueAccumulator parent, full;
        nnue_refresh(board, full); parent = full;
        check(board, parent, full);
        for (int ply = 0; ply < 80; ++ply) {
            chess::Movelist legal; chess::movegen::legalmoves(legal, board);
            if (legal.empty()) break;
            const auto snapshot = parent; const auto board_copy = board;
            const int begin = ply == 0 ? 0 : int(rng() % legal.size());
            const int end = ply == 0 ? int(legal.size()) : begin + 1;
            for (int i = begin; i < end; ++i) {
                const auto move = legal[i]; const auto piece = board.at(move.from());
                std::string kind = board.isCapture(move) ? "capture" : "quiet";
                if (piece.type() == chess::PieceType::KING) kind = "king";
                if (move.typeOf() == chess::Move::CASTLING) kind = "castling";
                if (move.typeOf() == chess::Move::ENPASSANT) kind = "ep";
                if (move.typeOf() == chess::Move::PROMOTION) kind = "promotion";
                const auto delta = nnue_move_delta(board, move);
                board.makeMove<true>(move);
                if (kind == "quiet" && !(board_copy.castlingRights() == board.castlingRights())) kind = "rights";
                NnueAccumulator expected, child;
                nnue_update_move(full, board, delta, expected);
                // Nonzero unused lanes/metadata catch reads of uninitialized child data.
                for (auto& side : child.values) side.fill(12345.f);
                nnue_update_search(parent, board, delta, child);
                check(board, child, expected);
                const auto states = nnue_search_states(board);
                int removed_states = 0, added_states = 0;
                for (int j = 0; j < full.features.count; ++j) {
                    const int f = full.features.active[0][j];
                    if (f >= 768 && std::find(states.active[0].begin(), states.active[0].begin()+states.count, f) == states.active[0].begin()+states.count) ++removed_states;
                }
                for (int j = 0; j < states.count; ++j)
                    if (!std::binary_search(full.features.active[0].begin(), full.features.active[0].begin()+full.features.count, states.active[0][j])) ++added_states;
                if (edges.size() < 9000) edges.push_back({board_copy, board, move, parent, delta, states, kind, false,
                    delta.removed_count + delta.added_count + removed_states + added_states});
                board.unmakeMove(move);
                if (!board.fullyEquals(board_copy) || std::memcmp(&parent, &snapshot, sizeof(parent)))
                    throw std::runtime_error("Sibling restore");
            }
            if (!board.inCheck()) {
                board.makeNullMove(); NnueAccumulator child, expected;
                nnue_update_move(full, board, {}, expected);
                nnue_update_search(parent, board, {}, child); check(board, child, expected);
                auto states = nnue_search_states(board);
                int removed = 0;
                for (int j = 0; j < full.features.count; ++j) removed += full.features.active[0][j] >= 772;
                edges.push_back({board_copy, board, {}, parent, {}, states, "null", true, removed});
                board.unmakeNullMove();
                if (!board.fullyEquals(board_copy)) throw std::runtime_error("Null restore");
            }
            auto move = legal[rng() % legal.size()];
            auto delta = nnue_move_delta(board, move); board.makeMove<true>(move);
            NnueAccumulator child, expected;
            nnue_update_move(full, board, delta, expected);
            nnue_update_search(parent, board, delta, child); check(board, child, expected);
            full = expected; parent = child;
        }
    }
}
using Clock = std::chrono::steady_clock;
template<class T> inline void consume(const T& value) {
    // Require every iteration's actual object writes, including isolated copy
    // and metadata loops. A final checksum alone could allow dead-store removal.
    __asm__ volatile("" : : "m"(value) : "memory");
}
template<class F> double timed(const std::vector<const Edge*>& group, int n, F fn) {
    for (int i = 0; i < 1000; ++i) fn(*group[i % group.size()]);
    const auto start = Clock::now();
    for (int i = 0; i < n; ++i) { fn(*group[i % group.size()]); std::atomic_signal_fence(std::memory_order_seq_cst); }
    return std::chrono::duration<double, std::nano>(Clock::now() - start).count() / n;
}
int main(int argc, char** argv) {
    nnue_set_kernel("clip"); prepare();
    std::cout << std::setprecision(12);
    if (argc < 2) return 2;
    if (std::string(argv[1]) == "--verify") {
        std::map<std::string,int> counts;
        for (const auto& e : edges) ++counts[e.kind];
        std::cout << "{\"passed\":true,\"digest\":\"" << digest << "\",\"edges\":" << edges.size() << ",\"kinds\":{";
        bool first = true;
        for (const auto& [k,v] : counts) { if (!first) std::cout << ','; first=false; std::cout << '"' << k << "\":" << v; }
        std::cout << "},\"frame_bytes\":" << sizeof(NnueAccumulator) << ",\"state_temporary_bytes\":" << sizeof(NnueSearchFeatures) << "}\n";
        return 0;
    }
    if (std::string(argv[1]) != "--bench") return 2;
    int n = argc > 2 ? std::stoi(argv[2]) : 100000;
    std::map<std::string,std::vector<const Edge*>> groups;
    for (const auto& e : edges) { groups[e.kind].push_back(&e); groups["mixed"].push_back(&e);
        if (e.parent.features.count >= 28) groups["high_features"].push_back(&e); }
    NnueAccumulator output; NnueDelta delta; NnueSearchFeatures states;
    std::cout << "{\"digest\":\"" << digest << "\",\"edge_bytes\":" << sizeof(Edge)
              << ",\"state_slot_bytes\":" << sizeof(NnueFeatures) << ",\"cases\":["; bool first = true;
    for (const auto& [kind,group] : groups) {
        double rows = 0; for (auto e : group) rows += e->rows * 2; rows /= group.size();
        double total = timed(group,n,[&](const Edge& e) { auto d = e.null_edge ? NnueDelta{} : nnue_move_delta(e.before,e.move); nnue_update_search(e.parent,e.after,d,output); consume(output.values); });
        sink += static_cast<unsigned>(output.values[0][0]*1000000+100000000);
        double update = timed(group,n,[&](const Edge& e) { nnue_update_search(e.parent,e.after,e.delta,output); consume(output.values); });
        sink += static_cast<unsigned>(output.values[1][1]*1000000+100000000);
        double prepared = timed(group,n,[&](const Edge& e) { nnue_update_search_states(e.parent,e.states,e.delta,output); consume(output.values); });
        sink += static_cast<unsigned>(output.values[0][2]*1000000+100000000);
        double state = timed(group,n,[&](const Edge& e) { states=nnue_search_states(e.after); consume(states); }); sink += states.count;
        double indexing = timed(group,n,[&](const Edge& e) { if (!e.null_edge) delta=nnue_move_delta(e.before,e.move); consume(delta); }); sink += delta.added_count;
        double copy = timed(group,n,[&](const Edge& e) { output.values=e.parent.values; consume(output.values); }); sink += static_cast<unsigned>(output.values[0][0]*1000000+100000000);
        double metadata = timed(group,n,[&](const Edge& e) { for (int p=0;p<2;++p) std::copy_n(e.states.active[p].begin(), e.states.count, output.features.active[p].begin()); output.features.count=e.states.count; consume(output.features); }); sink += output.features.count;
        if (!first) std::cout << ','; first=false;
        std::cout << "{\"kind\":\"" << kind << "\",\"edges\":" << group.size() << ",\"rows_both_perspectives\":" << rows
                  << ",\"total_ns\":" << total << ",\"update_ns\":" << update << ",\"prepared_update_ns\":" << prepared
                  << ",\"state_ns\":" << state << ",\"index_ns\":" << indexing << ",\"copy_reference_ns\":" << copy
                  << ",\"metadata_reference_ns\":" << metadata << '}';
    }
    std::cout << "],\"sink\":" << sink << "}\n";
}
