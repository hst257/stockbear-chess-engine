// Development-only microbenchmarks. Search binaries never link this entry point.
#include "nnue.hpp"
#include "evaluation.hpp"
#include "diagnostics.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <string>
#include <random>
#include <cmath>
#include <stdexcept>
#include <cstring>
#if defined(__x86_64__) || defined(__i386__)
#include <cpuid.h>
#endif
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#endif

template<class F> double time_calls(int n, F function) {
    const auto begin = std::chrono::steady_clock::now();
    for (int i = 0; i < n; ++i) { function(i); std::atomic_signal_fence(std::memory_order_seq_cst); }
    return double(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now() - begin).count()) / n;
}

int main(int argc, char** argv) {
    using namespace chesslab;
    std::cout << std::setprecision(10);
    if (argc >= 2 && std::string(argv[1]) == "--verify-throughput") {
        if (argc > 2) nnue_set_kernel(argv[2]);
        std::mt19937 random(20261015);
        int transitions = 0, nulls = 0;
        const char* fixtures[] = {
            chess::constants::STARTPOS,
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
            "rnbqkbnr/1pp1ppp1/p6p/2Pp4/8/5N2/PP1PPPPP/RNBQKB1R w KQkq d6 0 4",
            "r6k/1P6/8/8/8/8/8/K7 w - - 0 1",
            "7k/4P3/8/8/8/8/5p2/K7 w - - 0 1",
            "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1"};
        auto check = [&](const chess::Board& board, const NnueAccumulator& expected, const NnueAccumulator& actual) {
            for (int p = 0; p < 2; ++p) {
                if (std::memcmp(expected.values[p].data(), actual.values[p].data(), nnue_width() * sizeof(float)))
                    throw std::runtime_error("Search update changed float accumulator bits");
                if (nnue_quantized() && expected.quantized[p] != actual.quantized[p])
                    throw std::runtime_error("Search update changed integer lanes");
            }
            const float a = nnue_side_to_move(board, expected), b = nnue_side_to_move(board, actual);
            if (std::memcmp(&a, &b, sizeof(float)) || nnue_white_score(board, expected) != nnue_white_score(board, actual))
                throw std::runtime_error("Search update changed score bits");
        };
        for (auto fen : fixtures) for (int walk = 0; walk < 40; ++walk) {
            chess::Board board(fen);
            NnueAccumulator full, compact;
            nnue_refresh(board, full); compact = full;
            for (int ply = 0; ply < 120; ++ply) {
                chess::Movelist moves; chess::movegen::legalmoves(moves, board);
                if (moves.empty()) break;
                const auto before = board;
                const auto parent_snapshot = compact;
                const int begin = ply == 0 ? 0 : int(random() % moves.size());
                const int end = ply == 0 ? int(moves.size()) : begin + 1;
                for (int i = begin; i < end; ++i) {
                    const auto delta = nnue_move_delta(board, moves[i]);
                    board.makeMove<true>(moves[i]);
                    NnueAccumulator expected, actual;
                    nnue_update_move(full, board, delta, expected);
                    nnue_update_search(compact, board, delta, actual);
                    check(board, expected, actual); ++transitions;
                    board.unmakeMove(moves[i]);
                    if (!board.fullyEquals(before) || compact.values != parent_snapshot.values ||
                        compact.features.active != parent_snapshot.features.active || compact.features.count != parent_snapshot.features.count)
                        throw std::runtime_error("Search update mutated sibling parent");
                }
                if (!board.inCheck()) {
                    board.makeNullMove();
                    NnueAccumulator expected, actual;
                    nnue_update_move(full, board, {}, expected);
                    nnue_update_search(compact, board, {}, actual);
                    check(board, expected, actual); ++nulls;
                    board.unmakeNullMove();
                    if (!board.fullyEquals(before)) throw std::runtime_error("Null board restore");
                }
                const auto move = moves[random() % moves.size()];
                const auto delta = nnue_move_delta(board, move);
                board.makeMove<true>(move);
                NnueAccumulator expected, actual;
                nnue_update_move(full, board, delta, expected);
                nnue_update_search(compact, board, delta, actual);
                check(board, expected, actual);
                full = expected; compact = actual;
            }
        }
        std::cout << "{\"transitions\":" << transitions << ",\"nulls\":" << nulls << ",\"bitwise_exact\":true}\n";
        return 0;
    }
#ifdef CHESSLAB_DIAGNOSTICS
    if (argc == 2 && std::string(argv[1]) == "--diagnostics-verify") {
        // Exact synthetic oracle: an unused ancestor has evaluated children;
        // a null sibling is an unused leaf; reusing a ply retires it once.
        namespace d = chesslab::diagnostics;
        const unsigned width = nnue_width();
        const std::uint64_t copy = sizeof(NnueFeatures) + 2ULL * width * sizeof(float);
        d::reset(true, sizeof(NnueAccumulator), 65 * sizeof(NnueAccumulator));
        auto prepare = [&](int ply, unsigned rows, bool null_edge = false) {
            d::rows(rows, width, sizeof(float)); d::copied(copy);
            d::next_null = null_edge; d::prepare(ply);
        };
        d::visit(0, false, false);
        prepare(1, 2); d::visit(1, false, false);
        prepare(2, 3); d::visit(2, true, false); d::evaluation(2); d::evaluation(2);
        prepare(2, 0, true); d::visit(2, true, true);
        prepare(2, 2); d::visit(2, false, false); d::evaluation(2);
        const auto r = d::finish();
        if (r.updates != 4 || r.copies != 4 || r.visits != 5 || r.qvisits != 2 ||
            r.evaluation_calls != 3 || r.evaluated_visits != 2 || r.evaluated_frames != 2 ||
            r.unused_updates != 2 || r.unused_leaf_updates != 1 || r.unused_leaf_rows != 0 ||
            r.unused_q_updates != 1 || r.unused_null_updates != 1 || r.null_updates != 1 ||
            r.normal_updates != 2 || r.q_updates != 2 || r.unvisited_updates != 0 ||
            r.null_visits != 1 || r.evaluated_null_visits != 0 || r.evaluated_qvisits != 1 ||
            r.pending_edges != 4 || r.pending_rows != 9 || r.maximum_pending_rows != 5 ||
            r.maximum_pending_edges != 2 || r.delta_rows != 7 || r.zero_delta_updates != 1 ||
            r.copy_payload_bytes != 4 * copy || r.row_weight_bytes != 14ULL * width * sizeof(float) ||
            r.row_value_read_write_bytes != 28ULL * width * sizeof(float))
            throw std::runtime_error("Diagnostic counter oracle mismatch");
        std::cout << r.json() << '\n';
        return 0;
    }
#endif
    if (argc >= 2 && std::string(argv[1]) == "--verify") {
        if (argc > 2) nnue_set_kernel(argv[2]);
        std::mt19937 random(20261015);
        int transitions = 0, nulls = 0;
        float maximum = 0;
        const char* positions[] = {
            chess::constants::STARTPOS,
            "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
            "rnbqkbnr/1pp1ppp1/p6p/2Pp4/8/5N2/PP1PPPPP/RNBQKB1R w KQkq d6 0 4",
            "r6k/1P6/8/8/8/8/8/K7 w - - 0 1",
            "7k/4P3/8/8/8/8/5p2/K7 w - - 0 1",
            "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1"};
        auto check = [&](const chess::Board& board, const NnueAccumulator& a) {
            NnueAccumulator rebuilt;
            nnue_refresh(board, rebuilt);
            if (a.features.count != rebuilt.features.count) throw std::runtime_error("Feature count mismatch");
            for (int p = 0; p < 2; ++p) {
                for (int i = 0; i < a.features.count; ++i) if (a.features.active[p][i] != rebuilt.features.active[p][i]) throw std::runtime_error("Feature mismatch");
                for (int j = 0; j < nnue_width(); ++j) {
                    if (nnue_quantized()) {
                        if (a.quantized[p][j] != rebuilt.quantized[p][j]) throw std::runtime_error("Quantized accumulator mismatch");
                        continue;
                    }
                    maximum = std::max(maximum, std::abs(a.values[p][j] - rebuilt.values[p][j]));
                    if (maximum > .0001f) throw std::runtime_error("Accumulator lane mismatch");
                }
            }
            if (std::abs(nnue_side_to_move(board, a) - nnue_side_to_move(board, rebuilt)) > .01f) throw std::runtime_error("Score mismatch");
            if (std::abs(nnue_side_to_move(board, a) - nnue_reference_side_to_move(board, rebuilt)) > (nnue_quantized() ? 5.f : .01f)) throw std::runtime_error("Kernel mismatch");
        };
        for (auto fen : positions) for (int walk = 0; walk < 40; ++walk) {
            chess::Board board(fen);
            NnueAccumulator parent; nnue_refresh(board, parent);
            for (int ply = 0; ply < 120; ++ply) {
                chess::Movelist moves; chess::movegen::legalmoves(moves, board);
                if (moves.empty()) break;
                const auto before = board;
                const auto snapshot = parent;
                // Every sibling on the first ply, then one deterministic random child.
                const int start = ply == 0 ? 0 : int(random() % moves.size());
                const int end = ply == 0 ? int(moves.size()) : start + 1;
                for (int i = start; i < end; ++i) {
                    const auto delta = nnue_move_delta(board, moves[i]);
                    board.makeMove<true>(moves[i]);
                    NnueAccumulator child; nnue_update_move(parent, board, delta, child);
                    check(board, child); ++transitions;
                    board.unmakeMove(moves[i]);
                    if (!board.fullyEquals(before) || parent.values != snapshot.values || parent.quantized != snapshot.quantized || parent.features.active != snapshot.features.active) throw std::runtime_error("Sibling mutated parent");
                }
                if (!board.inCheck()) {
                    board.makeNullMove();
                    NnueAccumulator child; nnue_update_move(parent, board, {}, child);
                    check(board, child); ++nulls;
                    board.unmakeNullMove();
                    if (!board.fullyEquals(before)) throw std::runtime_error("Null restore mismatch");
                }
                const auto move = moves[random() % moves.size()];
                const auto delta = nnue_move_delta(board, move);
                board.makeMove<true>(move);
                NnueAccumulator child; nnue_update_move(parent, board, delta, child);
                parent = child;
            }
        }
        // Clipping boundaries and deliberately extreme unclipped sums.
        chess::Board board;
        for (int pattern = 0; pattern < 20; ++pattern) {
            NnueAccumulator acc;
            for (int p = 0; p < 2; ++p) for (int j = 0; j < nnue_width(); ++j) {
                acc.values[p][j] = pattern < 4 ? float(pattern - 1) : float(int(random() % 200001) - 100000) / 1000;
                acc.quantized[p][j] = std::lround(acc.values[p][j] * nnue_quant_first_scale());
            }
            if (std::abs(nnue_side_to_move(board, acc) - nnue_reference_side_to_move(board, acc)) > (nnue_quantized() ? 5.f : .01f)) throw std::runtime_error("Extreme kernel mismatch");
        }
        std::cout << "{\"transitions\":" << transitions << ",\"nulls\":" << nulls << ",\"max_lane_error\":" << maximum << "}\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--cpu") {
        bool avx2 = false, fma = false;
        std::string brand = "unknown";
#if defined(__x86_64__) || defined(__i386__)
        unsigned a, b, c, d;
        if (__get_cpuid(1, &a, &b, &c, &d) && (c & (1u << 27)) && (c & (1u << 28))) {
            unsigned low, high;
            __asm__ volatile("xgetbv" : "=a"(low), "=d"(high) : "c"(0));
            if ((low & 6) == 6) {
                fma = (c & (1u << 12)) != 0;
                __cpuid_count(7, 0, a, b, c, d);
                avx2 = (b & (1u << 5)) != 0;
            }
        }
        char name[49]{};
        if (__get_cpuid_max(0x80000000, nullptr) >= 0x80000004) {
            for (unsigned i = 0; i < 3; ++i) {
                __cpuid(0x80000002 + i, a, b, c, d);
                const unsigned words[] = {a, b, c, d};
                std::memcpy(name + 16 * i, words, sizeof(words));
            }
            brand = name;
        }
#endif
        std::cout << "{\"brand\":\"" << brand << "\",\"avx2_os_enabled\":" << (avx2 ? "true" : "false")
                  << ",\"fma_os_enabled\":" << (fma ? "true" : "false") << "}\n";
        return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "--batch") {
        if (argc > 2) nnue_set_kernel(argv[2]);
        std::string fen;
        while (std::getline(std::cin, fen)) {
            chess::Board board(fen);
            NnueAccumulator acc;
            nnue_refresh(board, acc);
            std::cout << nnue_side_to_move(board, acc) << '\n';
        }
        return 0;
    }
    if (argc < 2) return 1;
    chess::Board board(argv[1]), child = board;
    const int n = argc > 2 ? std::stoi(argv[2]) : 20000;
    if (argc > 3) nnue_set_kernel(argv[3]);
    if (n < 1) return 1;
    NnueAccumulator parent, output;
    nnue_refresh(board, parent);
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, child);
    const auto delta = moves.empty() ? NnueDelta{} : nnue_move_delta(board, moves[0]);
    if (!moves.empty()) child.makeMove<true>(moves[0]);
    volatile double checksum = 0;
    const auto features = time_calls(n, [&](int) { checksum += nnue_features(child).count; });
    const auto copy = time_calls(n, [&](int i) {
        for (int p = 0; p < 2; ++p) std::copy_n(parent.values[p].begin(), nnue_width(), output.values[p].begin());
        checksum += output.values[i % 2][i % nnue_width()];
    });
    const auto update = time_calls(n, [&](int) { nnue_update(parent, child, output); checksum += output.values[0][0]; });
    const auto move_update = time_calls(n, [&](int) { nnue_update_move(parent, child, delta, output); checksum += output.values[0][0]; });
    const auto refresh = time_calls(n, [&](int) { nnue_refresh(child, output); checksum += output.values[0][0]; });
    const auto head = time_calls(n, [&](int) { checksum += nnue_side_to_move(board, parent); });
    const auto classical = time_calls(n, [&](int) { checksum += evaluate(board, true, EvaluationOptions{}); });
    std::uint64_t working = 0, private_bytes = 0;
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS_EX counters{};
    if (GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters), sizeof(counters))) {
        working = counters.WorkingSetSize; private_bytes = counters.PrivateUsage;
    }
#endif
    std::cout << "{\"model\":\"" << nnue_model_name() << "\",\"sha256\":\"" << nnue_model_sha256()
              << "\",\"width\":" << nnue_width() << ",\"hidden\":" << nnue_hidden()
              << ",\"repeats\":" << n << ",\"feature_ns\":" << features << ",\"copy_ns\":" << copy
              << ",\"update_ns\":" << update << ",\"move_update_ns\":" << move_update << ",\"refresh_ns\":" << refresh
              << ",\"head_ns\":" << head << ",\"classical_ns\":" << classical
              << ",\"accumulator_bytes\":" << sizeof(NnueAccumulator)
              << ",\"working_set_bytes\":" << working << ",\"private_bytes\":" << private_bytes
              << ",\"checksum\":" << checksum << "}\n";
}
