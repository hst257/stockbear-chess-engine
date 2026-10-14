#include "evaluation.hpp"
#include "pst.hpp"

#include <algorithm>
#include <numeric>

namespace chesslab {
namespace {

static_assert(chess::Square(chess::Square::SQ_A1).index() == 0);
static_assert(chess::Square(chess::Square::SQ_H1).index() == 7);
static_assert(chess::Square(chess::Square::SQ_A8).index() == 56);
static_assert(chess::Square(chess::Square::SQ_H8).index() == 63);

chess::PieceType piece_type(int kind) {
    return chess::PieceType(static_cast<chess::PieceType::underlying>(kind));
}

int interpolate(int middlegame, int endgame, int phase) {
    const int numerator = middlegame * phase + endgame * (MAX_PHASE - phase);
    // Nearest centipawn; exact halves round away from zero for both colors.
    return (numerator + (numerator >= 0 ? MAX_PHASE / 2 : -MAX_PHASE / 2)) / MAX_PHASE;
}

}  // namespace

int Evaluation::positional() const {
    return std::accumulate(pst.begin(), pst.end(), 0);
}

int evaluate_material(const chess::Board& board) {
    int score = 0;
    for (int kind = 0; kind < 6; ++kind) {
        const auto type = piece_type(kind);
        score += PIECE_VALUES[kind] * (board.pieces(type, chess::Color::WHITE).count() -
                                      board.pieces(type, chess::Color::BLACK).count());
    }
    return score;
}

int game_phase(const chess::Board& board) {
    int phase = 0;
    for (int kind = 1; kind < 5; ++kind) {
        phase += PHASE_WEIGHTS[kind] * board.pieces(piece_type(kind)).count();
    }
    return std::clamp(phase, 0, MAX_PHASE);
}

Evaluation evaluate_breakdown(const chess::Board& board, bool use_pst) {
    Evaluation result;
    result.material = evaluate_material(board);
    result.phase = game_phase(board);
    if (!use_pst) return result;
    for (int kind = 0; kind < 6; ++kind) {
        for (const auto color : {chess::Color::WHITE, chess::Color::BLACK}) {
            auto squares = board.pieces(piece_type(kind), color);
            const int sign = color == chess::Color::WHITE ? 1 : -1;
            while (squares) {
                const int square = squares.pop();
                const int index = color == chess::Color::WHITE ? square : square ^ 56;
                const int mg = pst::MIDDLEGAME[kind][index];
                const int bonus = kind == chess::PieceType(chess::PieceType::KING)
                                    ? interpolate(mg, pst::KING_ENDGAME[index], result.phase) : mg;
                result.pst[kind] += sign * bonus;
            }
        }
    }
    return result;
}

int evaluate(const chess::Board& board, bool use_pst) {
    // Material-only search retains its original popcount-only fast path.
    return use_pst ? evaluate_breakdown(board, true).total() : evaluate_material(board);
}

}  // namespace chesslab
