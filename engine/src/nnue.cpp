#include "nnue.hpp"
#include "nnue_weights.hpp"
#include "transposition.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace chesslab {
namespace w = nnue_weights;

NnueFeatures nnue_features(const chess::Board& board) {
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
    output.features = nnue_features(board);
    for (int p = 0; p < 2; ++p) {
        auto& values = output.values[p];
        std::fill_n(values.begin(), w::WIDTH, 0.0f);
        for (int i = 0; i < output.features.count; ++i) {
            const auto* row = w::transform_weight + output.features.active[p][i] * w::WIDTH;
            for (int j = 0; j < w::WIDTH; ++j) values[j] += row[j];
        }
        for (int j = 0; j < w::WIDTH; ++j) values[j] += w::bias[j];
    }
}

void nnue_update(const NnueAccumulator& parent, const chess::Board& board, NnueAccumulator& output) {
    output.features = nnue_features(board);
    for (int p = 0; p < 2; ++p) {
        auto& values = output.values[p];
        std::copy_n(parent.values[p].begin(), w::WIDTH, values.begin());
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
            if (remove) for (int j = 0; j < w::WIDTH; ++j) values[j] -= row[j];
            else for (int j = 0; j < w::WIDTH; ++j) values[j] += row[j];
        }
    }
}

float nnue_side_to_move(const chess::Board& board, const NnueAccumulator& accumulator) {
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
