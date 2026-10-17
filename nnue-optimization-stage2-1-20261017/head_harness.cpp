// Development-only parity and paired timing harness, never application code.
#include "nnue.hpp"
#include "nnue_weights.hpp"
#include "stage1_head.hpp"
#include "transposition.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
using namespace chesslab;

const char* FIXTURES[] = {
    chess::constants::STARTPOS,
    "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7",
    "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
    "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
    "7k/4P3/8/8/8/8/5p2/K7 w - - 0 1",
    "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1"};

std::uint32_t bits(float value) {
    std::uint32_t result; std::memcpy(&result, &value, 4); return result;
}
float from_bits(std::uint32_t value) {
    float result; std::memcpy(&result, &value, 4); return result;
}
std::uint64_t checks = 0, nan_heads = 0;
void check(const chess::Board& board, const NnueAccumulator& frame) {
    nnue_set_kernel("scalar");
    const float original = nnue_side_to_move(board, frame);
    const int expected = std::isfinite(original) ? nnue_white_score(board, frame) : 0;
    nnue_set_kernel("clip");
    const float candidate = nnue_side_to_move(board, frame);
    if (bits(original) != bits(candidate))
        throw std::runtime_error("Head bit mismatch: " + std::to_string(bits(original)) + " vs " + std::to_string(bits(candidate)));
    if (std::isfinite(original) && expected != nnue_white_score(board, frame))
        throw std::runtime_error("White CP mismatch");
    if (std::isnan(original)) ++nan_heads;
    ++checks;
}

void parity(const char* golden_file) {
    std::map<std::string, std::uint64_t> moves_count;
    std::mt19937 rng(20261017);
    std::ifstream input(golden_file);
    if (!input) throw std::runtime_error("Missing golden FEN fixture file");
    std::string fen; int golden = 0;
    while (std::getline(input, fen)) if (!fen.empty()) {
        chess::Board board(fen); NnueAccumulator frame; nnue_refresh(board, frame);
        check(board, frame); ++golden;
    }
    for (auto start : FIXTURES) for (int walk = 0; walk < 40; ++walk) {
        chess::Board board(start); NnueAccumulator frame; nnue_refresh(board, frame);
        for (int ply = 0; ply < 120; ++ply) {
            chess::Movelist legal; chess::movegen::legalmoves(legal, board);
            if (legal.empty()) break;
            const auto saved_board = board; const auto saved_frame = frame;
            const int begin = ply == 0 ? 0 : int(rng() % legal.size());
            const int end = ply == 0 ? int(legal.size()) : begin + 1;
            for (int i = begin; i < end; ++i) {
                auto move = legal[i]; const auto piece = board.at(move.from());
                const bool captured = board.isCapture(move);
                const auto delta = nnue_move_delta(board, move);
                board.makeMove<true>(move);
                NnueAccumulator child; nnue_update_search(frame, board, delta, child);
                check(board, child);
                ++moves_count["moves"];
                if (captured) ++moves_count["captures"];
                if (piece.type() == chess::PieceType::KING) ++moves_count["king"];
                if (move.typeOf() == chess::Move::CASTLING) ++moves_count["castling"];
                if (move.typeOf() == chess::Move::PROMOTION) ++moves_count["promotions"];
                if (move.typeOf() == chess::Move::ENPASSANT) ++moves_count["ep"];
                board.unmakeMove(move);
                if (!board.fullyEquals(saved_board) || std::memcmp(&frame, &saved_frame, sizeof(frame)))
                    throw std::runtime_error("Sibling parent restoration mismatch");
                check(board, frame);
            }
            if (!board.inCheck()) {
                board.makeNullMove(); NnueAccumulator child;
                nnue_update_search(frame, board, {}, child); check(board, child);
                board.unmakeNullMove(); ++moves_count["nulls"];
                if (!board.fullyEquals(saved_board)) throw std::runtime_error("Null restore mismatch");
            }
            const auto move = legal[rng() % legal.size()];
            const auto delta = nnue_move_delta(board, move); board.makeMove<true>(move);
            NnueAccumulator child; nnue_update_search(frame, board, delta, child); frame = child;
            check(board, frame);
        }
    }
    chess::Board board;
    const std::uint32_t edge_bits[] = {0,0x80000000,1,0x80000001,0x3f800000,0x3f7fffff,0x3f800001,
        0x7f7fffff,0xff7fffff,0x7f800000,0xff800000,0x7fc00001,0xffc12345,0x7f800001,0xff800001};
    std::uint64_t clipping_lanes = 0;
    for (std::uint32_t edge : edge_bits) {
        NnueAccumulator frame;
        for (auto& side : frame.values) side.fill(from_bits(edge));
        check(board, frame);
        for (int p = 0; p < 2; ++p) {
            alignas(64) float actual[NNUE_WIDTH];
            stage1::clip_inputs(frame.values[p].data(), actual, nnue_width());
            for (int j = 0; j < nnue_width(); ++j) {
                float expected = std::clamp(frame.values[p][j], 0.f, 1.f);
                if (bits(expected) != bits(actual[j])) throw std::runtime_error("Special input clip bits differ");
                ++clipping_lanes;
            }
        }
    }
    for (int sample = 0; sample < 20000; ++sample) {
        NnueAccumulator frame;
        for (auto& side : frame.values) for (float& v : side) {
            auto u = rng(); if ((u & 0x7f800000) == 0x7f800000) u ^= 0x00800000;
            v = from_bits(u);
        }
        check(board, frame); board.makeNullMove(); check(board, frame); board.unmakeNullMove();
    }
    // Exercise the unchanged score-conversion contract independently at values
    // the frozen small network may not naturally produce. This is not a new
    // model or a claim that every artificial CP is reachable by its weights.
    for (float cp : {-1.e20f,-30000.f,-29999.f,-1.5f,-.5f,-0.f,0.f,.5f,1.5f,29999.f,30000.f,1.e20f}) {
        const int score = int(std::lround(std::clamp(cp, float(-MATE_THRESHOLD+1), float(MATE_THRESHOLD-1))));
        if (std::abs(score) >= MATE_THRESHOLD) throw std::runtime_error("Mate-score clamp");
        if (std::abs(cp) == .5f && score != (cp < 0 ? -1 : 1)) throw std::runtime_error("Half CP rounding");
    }
    for (auto key : {"captures","king","castling","promotions","ep","nulls"})
        if (!moves_count[key]) throw std::runtime_error("Missing special-move coverage");
    std::cout << "{\"passed\":true,\"head_bit_comparisons\":" << checks << ",\"nan_head_comparisons\":" << nan_heads
              << ",\"special_clip_lane_comparisons\":" << clipping_lanes << ",\"golden_fens\":" << golden << ",\"mxcsr\":" << _mm_getcsr() << ",\"transitions\":{";
    bool first = true;
    for (auto [name, count] : moves_count) { if (!first)std::cout << ','; first=false; std::cout << '"' << name << "\":" << count; }
    std::cout << "}}\n";
}

volatile double checksum = 0;
void benchmark(const std::string& kernel, int size, int count, const char* fen = nullptr) {
    std::vector<NnueAccumulator> frames(size);
    std::vector<chess::Board> boards(size);
    std::mt19937 rng(20261017); chess::Board board;
    for (int i = 0; i < size; ++i) {
        if (fen) board = chess::Board(fen);
        else {
            chess::Movelist legal; chess::movegen::legalmoves(legal, board);
            if (i % 64 == 0 || legal.empty()) {
                board = chess::Board(FIXTURES[(i/64) % 6]); chess::movegen::legalmoves(legal, board);
            }
            board.makeMove<true>(legal[rng() % legal.size()]);
        }
        boards[i] = board; nnue_refresh(board, frames[i]);
    }
    nnue_set_kernel(kernel);
    for (int i = 0; i < 10000; ++i) checksum += nnue_side_to_move(boards[i%size], frames[i%size]);
    const auto start = std::chrono::steady_clock::now();
    for (int i = 0; i < count; ++i) {
        checksum += nnue_side_to_move(boards[i%size], frames[i%size]);
        std::atomic_signal_fence(std::memory_order_seq_cst);
    }
    const double ns = double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count()) / count;
    std::cout << "{\"ns\":" << ns << ",\"checksum\":" << checksum << ",\"kernel\":\"" << nnue_effective_kernel()
              << "\",\"frame_storage_bytes\":" << size*sizeof(NnueAccumulator) << "}\n";
}

int main(int argc, char** argv) {
    std::cout << std::setprecision(12);
    if (argc == 3 && std::string(argv[1]) == "--parity") parity(argv[2]);
    else if (argc == 6 && std::string(argv[1]) == "--bench") benchmark(argv[2], std::stoi(argv[3]), std::stoi(argv[4]), nullptr);
    else if (argc == 5 && std::string(argv[1]) == "--bench") benchmark(argv[2], std::stoi(argv[3]), std::stoi(argv[4]));
    else if (argc == 5 && std::string(argv[1]) == "--fen") benchmark(argv[2], 1, std::stoi(argv[4]), argv[3]);
    else throw std::runtime_error("Expected --parity FEN_FILE | --bench KERNEL FRAMES COUNT | --fen KERNEL FEN COUNT");
}
