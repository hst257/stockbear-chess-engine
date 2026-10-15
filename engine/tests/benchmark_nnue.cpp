// Development-only microbenchmarks. Search binaries never link this entry point.
#include "nnue.hpp"
#include "evaluation.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iomanip>
#include <iostream>
#include <string>
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
                auto* out = reinterpret_cast<unsigned*>(name + 16 * i);
                out[0] = a; out[1] = b; out[2] = c; out[3] = d;
            }
            brand = name;
        }
#endif
        std::cout << "{\"brand\":\"" << brand << "\",\"avx2_os_enabled\":" << (avx2 ? "true" : "false")
                  << ",\"fma_os_enabled\":" << (fma ? "true" : "false") << "}\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--batch") {
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
    if (n < 1) return 1;
    NnueAccumulator parent, output;
    nnue_refresh(board, parent);
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, child);
    if (!moves.empty()) child.makeMove<true>(moves[0]);
    volatile double checksum = 0;
    const auto features = time_calls(n, [&](int) { checksum += nnue_features(child).count; });
    const auto copy = time_calls(n, [&](int i) {
        for (int p = 0; p < 2; ++p) std::copy_n(parent.values[p].begin(), nnue_width(), output.values[p].begin());
        checksum += output.values[i % 2][i % nnue_width()];
    });
    const auto update = time_calls(n, [&](int) { nnue_update(parent, child, output); checksum += output.values[0][0]; });
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
              << ",\"update_ns\":" << update << ",\"refresh_ns\":" << refresh
              << ",\"head_ns\":" << head << ",\"classical_ns\":" << classical
              << ",\"accumulator_bytes\":" << sizeof(NnueAccumulator)
              << ",\"working_set_bytes\":" << working << ",\"private_bytes\":" << private_bytes
              << ",\"checksum\":" << checksum << "}\n";
}
