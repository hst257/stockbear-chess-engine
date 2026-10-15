#include "nnue.hpp"
#include "nnue_weights.hpp"
#include "transposition.hpp"
#include "profiling.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <cstdlib>
#if (defined(__x86_64__) || defined(__i386__)) && (defined(__GNUC__) || defined(__clang__))
#define CHESSLAB_X86_SIMD
#include <cpuid.h>
#include <immintrin.h>
#endif

namespace chesslab {
namespace w = nnue_weights;
namespace {
enum class Kernel { AUTO, REFERENCE, SCALAR, QUANT, QUANT_SIMD };
thread_local Kernel selected_kernel = Kernel::AUTO;
constexpr const char* KERNEL_NAMES[] = {"auto", "reference", "scalar", "quant", "quant-simd"};
}
void nnue_set_kernel(const std::string& name) {
    for (int i = 0; i < 5; ++i) if (name == KERNEL_NAMES[i]) {
        if (i >= 3 && !w::Q_ENABLED) throw std::invalid_argument("This model has no safe quantized representation");
        selected_kernel = static_cast<Kernel>(i); return;
    }
    throw std::invalid_argument("Unknown NNUE kernel");
}
const char* nnue_kernel() { return KERNEL_NAMES[static_cast<int>(selected_kernel)]; }
bool nnue_simd_available() {
    static const bool supported = [] {
        if (std::getenv("CHESSLAB_DISABLE_SIMD")) return false;
#ifdef CHESSLAB_X86_SIMD
        unsigned a, b, c, d;
        if (!__get_cpuid(1, &a, &b, &c, &d) || !(c & (1u << 27)) || !(c & (1u << 28))) return false;
        unsigned low, high;
        __asm__ volatile("xgetbv" : "=a"(low), "=d"(high) : "c"(0));
        if ((low & 6) != 6) return false;
        __cpuid_count(7, 0, a, b, c, d);
        return (b & (1u << 5)) != 0;
#else
        return false;
#endif
    }();
    return supported;
}
const char* nnue_effective_kernel() {
    if (selected_kernel == Kernel::AUTO) return "scalar";
    if (selected_kernel == Kernel::QUANT_SIMD && !nnue_simd_available()) return "quant";
    return nnue_kernel();
}
bool nnue_quantized() { return selected_kernel == Kernel::QUANT || selected_kernel == Kernel::QUANT_SIMD; }
int nnue_quant_first_scale() { return w::Q_FIRST_SCALE; }

namespace {
int reverse_feature(int index) {
    if (index < 768) return ((index / 384) ^ 1) * 384 + ((index % 384) ^ 56);
    return index < 772 ? 768 + ((index - 768) ^ 2) : index;
}
int piece_feature(chess::Piece piece, int square) {
    return (int(piece.color()) * 6 + int(piece.type())) * 64 + square;
}
// State-only extraction avoids traversing and sorting the board's pieces.
NnueFeatures state_features(const chess::Board& board) {
    NnueFeatures result;
    auto append = [&](int f) {
        result.active[0][result.count] = f;
        result.active[1][result.count++] = reverse_feature(f);
    };
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        const int home = c == 0 ? 0 : 56;
        if (board.kingSq(color).index() != home + 4) continue;
        for (int side = 0; side < 2; ++side) {
            const auto castle = side == 0 ? chess::Board::CastlingRights::Side::KING_SIDE : chess::Board::CastlingRights::Side::QUEEN_SIDE;
            if (board.castlingRights().has(color, castle) &&
                board.at(chess::Square(home + (side == 0 ? 7 : 0))) == chess::Piece(chess::PieceType::ROOK, color)) append(768 + 2 * c + side);
        }
    }
    if (board.enpassantSq() != chess::Square::NO_SQ) {
        chess::Movelist captures;
        chess::movegen::legalmoves<chess::movegen::MoveGenType::CAPTURE>(captures, board, chess::PieceGenType::PAWN);
        for (auto move : captures) if (move.typeOf() == chess::Move::ENPASSANT) {
            append(772 + board.enpassantSq().index() % 8); break;
        }
    }
    return result;
}
}

NnueDelta nnue_move_delta(const chess::Board& before, chess::Move move) {
    NnueDelta delta;
    auto remove = [&](chess::Piece pc, int sq) { delta.removed[delta.removed_count++] = piece_feature(pc, sq); };
    auto add = [&](chess::Piece pc, int sq) { delta.added[delta.added_count++] = piece_feature(pc, sq); };
    const auto pc = before.at(move.from());
    remove(pc, move.from().index());
    if (move.typeOf() == chess::Move::CASTLING) {
        const int rank = move.from().index() & ~7;
        const bool king_side = move.to() > move.from();
        const auto rook = before.at(move.to());
        remove(rook, move.to().index());
        add(pc, rank + (king_side ? 6 : 2));
        add(rook, rank + (king_side ? 5 : 3));
    } else {
        if (move.typeOf() == chess::Move::ENPASSANT) {
            const int sq = move.to().index() + (before.sideToMove() == chess::Color::WHITE ? -8 : 8);
            remove(before.at(chess::Square(sq)), sq);
        } else if (before.at(move.to()) != chess::Piece::NONE) remove(before.at(move.to()), move.to().index());
        add(move.typeOf() == chess::Move::PROMOTION ? chess::Piece(move.promotionType(), pc.color()) : pc, move.to().index());
    }
    return delta;
}

void nnue_update_move(const NnueAccumulator& parent, const chess::Board& after,
                      const NnueDelta& delta, NnueAccumulator& output) {
    profiling::Scope measured(profiling::NNUE_UPDATE);
    const auto states = state_features(after);
    const bool quant = nnue_quantized();
    output.features = parent.features;
    for (int p = 0; p < 2; ++p) {
        // Sort only the changed rows, preserving the reference arithmetic order.
        int changes[16], size = 0;
        auto change = [&](int f, bool remove) { changes[size++] = (f + 1) * (remove ? -1 : 1); };
        for (int i = 0; i < delta.removed_count; ++i) change(p == 0 ? delta.removed[i] : reverse_feature(delta.removed[i]), true);
        for (int i = 0; i < delta.added_count; ++i) change(p == 0 ? delta.added[i] : reverse_feature(delta.added[i]), false);
        const auto& previous = parent.features.active[p];
        for (int i = parent.features.count - 1; i >= 0 && previous[i] >= 768; --i) {
            bool found = false;
            for (int j = 0; j < states.count; ++j) found |= previous[i] == states.active[p][j];
            if (!found) change(previous[i], true);
        }
        for (int i = 0; i < states.count; ++i) {
            if (!std::binary_search(previous.begin(), previous.begin() + parent.features.count, states.active[p][i])) change(states.active[p][i], false);
        }
        std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); });
        auto& active = output.features.active[p];
        int count = parent.features.count;
        // Remove before inserting: a full 37-feature position must never need
        // an extra temporary slot when a new feature sorts before an old one.
        for (int i = 0; i < size; ++i) if (changes[i] < 0) {
            const int f = -changes[i] - 1;
            auto it = std::lower_bound(active.begin(), active.begin() + count, f);
            if (it == active.begin() + count || *it != f) throw std::logic_error("NNUE delta missing piece");
            std::move(it + 1, active.begin() + count, it); --count;
        }
        for (int i = 0; i < size; ++i) if (changes[i] > 0) {
            const int f = changes[i] - 1;
            auto it = std::lower_bound(active.begin(), active.begin() + count, f);
            std::move_backward(it, active.begin() + count, active.begin() + count + 1);
            *it = f; ++count;
        }
        auto& values = output.values[p];
        if (quant) std::copy_n(parent.quantized[p].begin(), w::WIDTH, output.quantized[p].begin());
        else std::copy_n(parent.values[p].begin(), w::WIDTH, values.begin());
        for (int i = 0; i < size; ++i) {
            const bool remove = changes[i] < 0;
            const int f = std::abs(changes[i]) - 1;
            if (quant) {
                const auto* row = w::q_transform_weight + f * w::WIDTH;
                if (remove) for (int j = 0; j < w::WIDTH; ++j) output.quantized[p][j] -= row[j];
                else for (int j = 0; j < w::WIDTH; ++j) output.quantized[p][j] += row[j];
            } else {
                const float* row = w::transform_weight + f * w::WIDTH;
                if (remove) for (int j = 0; j < w::WIDTH; ++j) values[j] -= row[j];
                else for (int j = 0; j < w::WIDTH; ++j) values[j] += row[j];
            }
        }
        if (p == 1) output.features.count = count;
    }
}

NnueFeatures nnue_features(const chess::Board& board) {
    profiling::Scope measured(profiling::NNUE_FEATURES);
    NnueFeatures result;
    auto append = [&](int white, int black) {
        if (result.count >= 37) throw std::invalid_argument("NNUE supports at most 37 active features");
        result.active[0][result.count] = static_cast<std::uint16_t>(white);
        result.active[1][result.count++] = static_cast<std::uint16_t>(black);
    };
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        for (int kind = 0; kind < 6; ++kind) {
            const auto type = chess::PieceType(static_cast<chess::PieceType::underlying>(kind));
            auto pieces = board.pieces(type, color);
            while (pieces) {
                const int square = pieces.pop();
                append((c * 6 + kind) * 64 + square,
                       ((1 - c) * 6 + kind) * 64 + (square ^ 56));
            }
        }
        // Match python-chess clean_castling_rights for orthodox chess.
        const int home = c == 0 ? 0 : 56;
        if (board.kingSq(color).index() == home + 4) {
            const auto rights = board.castlingRights();
            for (int side = 0; side < 2; ++side) {
                const auto castle = side == 0 ? chess::Board::CastlingRights::Side::KING_SIDE :
                                               chess::Board::CastlingRights::Side::QUEEN_SIDE;
                const auto rook_square = chess::Square(home + (side == 0 ? 7 : 0));
                if (rights.has(color, castle) && board.at(rook_square) == chess::Piece(chess::PieceType::ROOK, color))
                    append(768 + c * 2 + side, 768 + (1 - c) * 2 + side);
            }
        }
    }
    if (board.enpassantSq() != chess::Square::NO_SQ) {
        // Legal EP only: a pseudo-legal capture exposing the king is excluded.
        chess::Movelist captures;
        chess::movegen::legalmoves<chess::movegen::MoveGenType::CAPTURE>(captures, board, chess::PieceGenType::PAWN);
        for (const auto move : captures) {
            if (move.typeOf() == chess::Move::ENPASSANT) {
                const int feature = 772 + board.enpassantSq().index() % 8;
                append(feature, feature);
                break;
            }
        }
    }
    for (auto& features : result.active) std::sort(features.begin(), features.begin() + result.count);
    return result;
}

void nnue_refresh(const chess::Board& board, NnueAccumulator& output) {
    profiling::Scope measured(profiling::NNUE_REFRESH);
    output.features = nnue_features(board);
    for (int p = 0; p < 2; ++p) {
        auto& values = output.values[p];
        std::fill_n(values.begin(), w::WIDTH, 0.0f);
        for (int i = 0; i < output.features.count; ++i) {
            const auto* row = w::transform_weight + output.features.active[p][i] * w::WIDTH;
            for (int j = 0; j < w::WIDTH; ++j) values[j] += row[j];
        }
        for (int j = 0; j < w::WIDTH; ++j) values[j] += w::bias[j];
        if (nnue_quantized()) {
            std::copy_n(w::q_bias, w::WIDTH, output.quantized[p].begin());
            for (int i = 0; i < output.features.count; ++i) {
                const auto* row = w::q_transform_weight + output.features.active[p][i] * w::WIDTH;
                for (int j = 0; j < w::WIDTH; ++j) output.quantized[p][j] += row[j];
            }
        }
    }
}

void nnue_update(const NnueAccumulator& parent, const chess::Board& board, NnueAccumulator& output) {
    profiling::Scope measured(profiling::NNUE_UPDATE);
    output.features = nnue_features(board);
    const bool quant = nnue_quantized();
    for (int p = 0; p < 2; ++p) {
        auto& values = output.values[p];
        if (quant) std::copy_n(parent.quantized[p].begin(), w::WIDTH, output.quantized[p].begin());
        else std::copy_n(parent.values[p].begin(), w::WIDTH, values.begin());
        int old = 0, next = 0;
        const auto& previous = parent.features.active[p];
        const auto& current = output.features.active[p];
        while (old < parent.features.count || next < output.features.count) {
            if (old < parent.features.count && next < output.features.count && previous[old] == current[next]) {
                ++old;
                ++next;
                continue;
            }
            const bool remove = old < parent.features.count &&
                (next >= output.features.count || previous[old] < current[next]);
            const int index = remove ? previous[old++] : current[next++];
            const auto* row = w::transform_weight + index * w::WIDTH;
            if (quant) {
                const auto* qrow = w::q_transform_weight + index * w::WIDTH;
                if (remove) for (int j = 0; j < w::WIDTH; ++j) output.quantized[p][j] -= qrow[j];
                else for (int j = 0; j < w::WIDTH; ++j) output.quantized[p][j] += qrow[j];
            } else {
                if (remove) for (int j = 0; j < w::WIDTH; ++j) values[j] -= row[j];
                else for (int j = 0; j < w::WIDTH; ++j) values[j] += row[j];
            }
        }
    }
}

float nnue_reference_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator) {
    profiling::Scope measured(profiling::NNUE_HEAD);
    float input[2 * w::WIDTH];
    const int first = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
    for (int p = 0; p < 2; ++p)
        for (int j = 0; j < w::WIDTH; ++j)
            input[p * w::WIDTH + j] = std::clamp(accumulator.values[p == 0 ? first : 1 - first][j], 0.0f, 1.0f);
    float output = w::fc2_bias[0];
    for (int h = 0; h < w::HIDDEN; ++h) {
        float hidden = w::fc1_bias[h];
        for (int j = 0; j < 2 * w::WIDTH; ++j) hidden += w::fc1_weight[h * 2 * w::WIDTH + j] * input[j];
        output += w::fc2_weight[h] * std::clamp(hidden, 0.0f, 1.0f);
    }
    return output * 400.0f;
}

// Dot products are bounded at embedding time, including bias and all signs.
static std::int32_t scalar_dot(const std::int16_t* a, const std::int16_t* b, int count) {
    std::int32_t sum = 0;
    for (int i = 0; i < count; ++i) sum += std::int32_t(a[i]) * b[i];
    return sum;
}
#ifdef CHESSLAB_X86_SIMD
__attribute__((target("avx2")))
static std::int32_t integer_simd_dot(const std::int16_t* a, const std::int16_t* b, int count) {
    auto sum = _mm256_setzero_si256();
    int i = 0;
    for (; i + 16 <= count; i += 16) sum = _mm256_add_epi32(sum,
        _mm256_madd_epi16(_mm256_loadu_si256(reinterpret_cast<const __m256i*>(a + i)),
                         _mm256_loadu_si256(reinterpret_cast<const __m256i*>(b + i))));
    alignas(32) std::int32_t lanes[8];
    _mm256_store_si256(reinterpret_cast<__m256i*>(lanes), sum);
    std::int32_t result = 0;
    for (int lane : lanes) result += lane;
    for (; i < count; ++i) result += std::int32_t(a[i]) * b[i];
    return result;
}
#endif
static float quantized_head(const chess::Board& board, const NnueAccumulator& accumulator) {
    constexpr int qa = w::Q_ACTIVATION_SCALE;
    std::int16_t input[2 * w::WIDTH], hidden[w::HIDDEN];
    const int first = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
    for (int p = 0; p < 2; ++p) for (int j = 0; j < w::WIDTH; ++j) {
        const auto value = std::clamp(accumulator.quantized[p == 0 ? first : 1 - first][j], 0, w::Q_FIRST_SCALE);
        input[p * w::WIDTH + j] = (value * qa + w::Q_FIRST_SCALE / 2) / w::Q_FIRST_SCALE;
    }
    auto dot = scalar_dot;
#ifdef CHESSLAB_X86_SIMD
    if (selected_kernel == Kernel::QUANT_SIMD && nnue_simd_available()) dot = integer_simd_dot;
#endif
    for (int h = 0; h < w::HIDDEN; ++h) {
        const auto value = w::q_fc1_bias[h] + dot(input, w::q_fc1_weight + h * 2 * w::WIDTH, 2 * w::WIDTH);
        hidden[h] = (std::clamp(value, 0, qa * w::Q_HEAD_WEIGHT_SCALE) + w::Q_HEAD_WEIGHT_SCALE / 2) / w::Q_HEAD_WEIGHT_SCALE;
    }
    const auto result = w::q_fc2_bias[0] + dot(hidden, w::q_fc2_weight, w::HIDDEN);
    return float(result) * (400.0f / (qa * w::Q_OUTPUT_WEIGHT_SCALE));
}

float nnue_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator) {
    if (selected_kernel == Kernel::REFERENCE) return nnue_reference_side_to_move(board, accumulator);
    profiling::Scope measured(profiling::NNUE_HEAD);
    if (nnue_quantized()) return quantized_head(board, accumulator);
    // Each neuron's additions retain their original order. Parallel neurons
    // give the compiler independent lanes without reassociating a dot product.
    alignas(64) float hidden[w::HIDDEN];
    std::copy_n(w::fc1_bias, w::HIDDEN, hidden);
    const int first = board.sideToMove() == chess::Color::WHITE ? 0 : 1;
    for (int p = 0; p < 2; ++p) for (int j = 0; j < w::WIDTH; ++j) {
        const float input = std::clamp(accumulator.values[p == 0 ? first : 1 - first][j], 0.0f, 1.0f);
        const auto* weights = w::fc1_transposed + (p * w::WIDTH + j) * w::HIDDEN;
        for (int h = 0; h < w::HIDDEN; ++h) hidden[h] += weights[h] * input;
    }
    float output = w::fc2_bias[0];
    for (int h = 0; h < w::HIDDEN; ++h) output += w::fc2_weight[h] * std::clamp(hidden[h], 0.0f, 1.0f);
    return output * 400.0f;
}

int nnue_white_score(const chess::Board& board, const NnueAccumulator& accumulator) {
    const float cp = nnue_side_to_move(board, accumulator) * (board.sideToMove() == chess::Color::WHITE ? 1 : -1);
    // Learned static values must never masquerade as proven search mates.
    return static_cast<int>(std::lround(std::clamp(cp, float(-MATE_THRESHOLD + 1), float(MATE_THRESHOLD - 1))));
}
int nnue_width() { return w::WIDTH; }
int nnue_hidden() { return w::HIDDEN; }
const char* nnue_model_name() { return w::NAME; }
const char* nnue_model_sha256() { return w::SHA256; }

}  // namespace chesslab
