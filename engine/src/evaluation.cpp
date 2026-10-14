#include "evaluation.hpp"
#include "pst.hpp"
#include "evaluation_masks.hpp"
#include "profiling.hpp"

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

// One table walk serves both modes. The template preserves legacy per-king
// rounding while advanced evaluation retains raw MG/EG scores until the end.
template<bool Advanced, bool Diagnostics = true>
void evaluate_pst(const chess::Board& board, Evaluation& result) {
    profiling::Scope measured(profiling::MATERIAL_PST);
    for (int kind = 0; kind < 6; ++kind) {
        EvalScore piece_score;
        for (const auto color : {chess::Color::WHITE, chess::Color::BLACK}) {
            auto squares = board.pieces(piece_type(kind), color);
            const int sign = color == chess::Color::WHITE ? 1 : -1;
            while (squares) {
                const int square = squares.pop();
                const int index = color == chess::Color::WHITE ? square : square ^ 56;
                const int mg = pst::MIDDLEGAME[kind][index];
                const int eg = kind == 5 ? pst::KING_ENDGAME[index] : mg;
                if constexpr (Advanced) piece_score.add(mg, eg, sign);
                else result.pst[kind] += sign * (kind == 5 ? interpolate(mg, eg, result.phase) : mg);
            }
        }
        if constexpr (Advanced) {
            if constexpr (Diagnostics) result.pst[kind] = taper(piece_score, result.phase);
            result.components[PST].add(piece_score.middlegame, piece_score.endgame);
        }
    }
}

struct EvalContext {
    chess::Bitboard pawns[2];
    chess::Bitboard pawn_attacks[2];
    chess::Bitboard passers[2];
    chess::Bitboard attacks[2];
    chess::Bitboard double_attacks[2];
    chess::Bitboard piece_attacks[2][6];
    int zone_attackers[2]{};
    int zone_units[2]{};
    explicit EvalContext(const chess::Board& board) {
        for (int c = 0; c < 2; ++c) {
            const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
            pawns[c] = board.pieces(chess::PieceType::PAWN, color);
            auto p = pawns[c];
            while (p) {
                const auto attacks = chess::attacks::pawn(color, chess::Square(p.pop()));
                double_attacks[c] |= pawn_attacks[c] & attacks;
                pawn_attacks[c] |= attacks;
            }
        }
    }
};

void build_attacks(const chess::Board& board, EvalContext& ctx) {
    profiling::Scope measured(profiling::ATTACKS);
    constexpr int attack_weight[] = {0, 2, 2, 3, 5, 0};
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        const auto king_attacks = chess::attacks::king(board.kingSq(color));
        ctx.double_attacks[c] |= ctx.pawn_attacks[c] & king_attacks;
        ctx.attacks[c] = ctx.pawn_attacks[c] | king_attacks;
        const auto enemy_king = board.kingSq(~color);
        const auto zone = chess::attacks::king(enemy_king) | chess::Bitboard::fromSquare(enemy_king);
        for (int kind = 1; kind <= 4; ++kind) {
            auto pieces = board.pieces(piece_type(kind), color);
            while (pieces) {
                const auto sq = chess::Square(pieces.pop());
                chess::Bitboard attacks;
                switch (kind) {
                    case 1: attacks = chess::attacks::knight(sq); break;
                    case 2: attacks = chess::attacks::bishop(sq, board.occ()); break;
                    case 3: attacks = chess::attacks::rook(sq, board.occ()); break;
                    default: attacks = chess::attacks::queen(sq, board.occ()); break;
                }
                ctx.double_attacks[c] |= ctx.attacks[c] & attacks;
                ctx.attacks[c] |= attacks;
                ctx.piece_attacks[c][kind] |= attacks;
                const int hits = (attacks & zone).count();
                if (hits) {
                    ++ctx.zone_attackers[c];
                    ctx.zone_units[c] += attack_weight[kind] * std::min(hits, 3);
                }
            }
        }
    }
}

void evaluate_mobility_outposts(const chess::Board& board, const EvalContext& ctx, Evaluation& result,
                                const EvaluationOptions& options) {
    constexpr int mg_weight[] = {0, 3, 3, 2, 1, 0};
    constexpr int eg_weight[] = {0, 3, 4, 3, 1, 0};
    constexpr int neutral[] = {0, 4, 6, 7, 12, 0};
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        const int sign = c == 0 ? 1 : -1;
        const auto safe = ~board.us(color) & ~ctx.pawn_attacks[1 - c] &
                          ~chess::attacks::king(board.kingSq(~color)) &
                          (~ctx.attacks[1 - c] | ctx.double_attacks[c]);
        if (options.uses(MOBILITY)) {
            for (int kind = 1; kind <= 4; ++kind) {
                // Union counts distinct useful destinations, avoiding inflated
                // bonuses when several pieces attack the same squares.
                const int count = (ctx.piece_attacks[c][kind] & safe).count() -
                                  neutral[kind] * board.pieces(piece_type(kind), color).count();
                result.components[MOBILITY].add(count * mg_weight[kind], count * eg_weight[kind], sign);
            }
        }
        if (!options.uses(OUTPOSTS)) continue;
        auto knights = board.pieces(chess::PieceType::KNIGHT, color);
        while (knights) {
            const int sq = knights.pop(), f = sq % 8, rank = c == 0 ? sq / 8 : 7 - sq / 8;
            if (rank >= 3 && rank <= 5 && f > 0 && f < 7 && ctx.pawn_attacks[c].check(sq) &&
                !(ctx.pawns[1 - c] & eval_masks::FORWARD[c][sq] & eval_masks::adjacent(f)))
                result.components[OUTPOSTS].add(18, 12, sign);
        }
    }
}

void evaluate_king_safety(const chess::Board& board, const EvalContext& ctx, Evaluation& result) {
    profiling::Scope measured(profiling::KING_SAFETY);
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        int enemy_phase = 0;
        for (int kind = 1; kind <= 4; ++kind)
            enemy_phase += PHASE_WEIGHTS[kind] * board.pieces(piece_type(kind), ~color).count();
        if (enemy_phase == 0) continue;
        const int king = board.kingSq(color).index(), rank = king / 8, file = king % 8;
        const int step = c == 0 ? 1 : -1;
        int penalty = 0;
        for (int f = std::max(0, file - 1); f <= std::min(7, file + 1); ++f) {
            const int near = rank + step, far = rank + 2 * step;
            const bool near_pawn = near >= 0 && near < 8 && ctx.pawns[c].check(near * 8 + f);
            const bool far_pawn = far >= 0 && far < 8 && ctx.pawns[c].check(far * 8 + f);
            penalty += near_pawn ? 0 : far_pawn ? 5 : 12;
            const auto mask = eval_masks::file(f);
            if (!(ctx.pawns[c] & mask)) penalty += (ctx.pawns[1 - c] & mask) ? 8 : 12;
        }
        const auto zone = chess::attacks::king(chess::Square(king)) | chess::Bitboard::fromSquare(king);
        const int attackers = std::min(ctx.zone_attackers[1 - c], 4);
        penalty += ctx.zone_units[1 - c] * attackers * 2;
        penalty += (ctx.pawn_attacks[1 - c] & zone).count() * 2;
        const auto major_attacks = ctx.piece_attacks[1 - c][3] | ctx.piece_attacks[1 - c][4];
        penalty += (major_attacks & zone & ~ctx.pawn_attacks[c]).count() * 3;
        // Safety is MG-only, then reduced further by the enemy's remaining
        // attacking material. No castling-right or side-to-move assumptions.
        result.components[KING_SAFETY].add(-penalty * std::min(enemy_phase, 12) / 12, 0, c == 0 ? 1 : -1);
    }
}

void evaluate_space(const chess::Board& board, const EvalContext& ctx, Evaluation& result) {
    for (int c = 0; c < 2; ++c) {
        const int sign = c == 0 ? 1 : -1;
        const auto safe_control = ctx.attacks[c] & ~ctx.pawn_attacks[1 - c] &
                                  (~ctx.attacks[1 - c] | ctx.pawn_attacks[c]);
        const int center = (safe_control & eval_masks::CENTER).count();
        const auto territory = c == 0 ? eval_masks::WHITE_SPACE : eval_masks::BLACK_SPACE;
        const int space = (safe_control & ctx.pawn_attacks[c] & territory & ~board.occ()).count();
        int supported = 0;
        auto pawns = ctx.pawns[c] & ctx.pawn_attacks[c] & ~ctx.attacks[1 - c];
        while (pawns) {
            const int sq = pawns.pop(), rank = c == 0 ? sq / 8 : 7 - sq / 8;
            if (sq % 8 >= 2 && sq % 8 <= 5 && rank >= 3 && rank <= 5) ++supported;
        }
        result.components[SPACE].add(2 * center + space + 3 * supported, center, sign);
    }
}

int king_distance(int a, int b) {
    return std::max(std::abs(a / 8 - b / 8), std::abs(a % 8 - b % 8));
}

void evaluate_endgame(const chess::Board& board, const EvalContext& ctx, Evaluation& result) {
    profiling::Scope measured(profiling::ENDGAME);
    const int kings[] = {board.kingSq(chess::Color::WHITE).index(), board.kingSq(chess::Color::BLACK).index()};
    for (int c = 0; c < 2; ++c) {
        const int sign = c == 0 ? 1 : -1;
        int activity = 0, targets = 0;
        auto enemy_pawns = ctx.pawns[1 - c];
        while (enemy_pawns) {
            activity += 7 - king_distance(kings[c], enemy_pawns.pop());
            ++targets;
        }
        if (targets) result.components[ENDGAME].add(0, 2 * activity / targets, sign);
        auto passers = ctx.passers[c];
        while (passers) {
            const int sq = passers.pop(), next = sq + (c == 0 ? 8 : -8);
            const int rank = c == 0 ? sq / 8 : 7 - sq / 8;
            // The next square is a local support target, not a promotion claim.
            const int proximity = king_distance(kings[1 - c], next) - king_distance(kings[c], next);
            result.components[ENDGAME].add(0, 2 * std::max(1, rank - 1) * proximity, sign);
        }
    }
    if (board.pieces(chess::PieceType::ROOK, chess::PieceType::QUEEN)) return;
    const auto minors = board.pieces(chess::PieceType::KNIGHT, chess::PieceType::BISHOP);
    const int white_minors = (minors & board.us(chess::Color::WHITE)).count();
    const int black_minors = (minors & board.us(chess::Color::BLACK)).count();
    if (!(ctx.pawns[0] | ctx.pawns[1]) && white_minors <= 1 && black_minors <= 1) {
        result.scale = 128;
    } else if (!board.pieces(chess::PieceType::KNIGHT) && white_minors == 1 && black_minors == 1 &&
               (ctx.pawns[0] | ctx.pawns[1]).count() <= 4) {
        const auto white = board.pieces(chess::PieceType::BISHOP, chess::Color::WHITE);
        const auto black = board.pieces(chess::PieceType::BISHOP, chess::Color::BLACK);
        if (bool(white & 0x55AA55AA55AA55AAULL) != bool(black & 0x55AA55AA55AA55AAULL)) result.scale = 192;
    }
}

void evaluate_pawns(const chess::Board& board, EvalContext& ctx, Evaluation& result,
                    const EvaluationOptions& options) {
    profiling::Scope measured(profiling::PAWNS);
    constexpr int passed_mg[] = {0, 0, 5, 12, 22, 38, 65, 0};
    constexpr int passed_eg[] = {0, 0, 10, 24, 45, 80, 130, 0};
    for (int c = 0; c < 2; ++c) {
        const int sign = c == 0 ? 1 : -1;
        if (options.uses(PAWNS)) {
            for (int f = 0; f < 8; ++f) {
                const int extra = (ctx.pawns[c] & eval_masks::file(f)).count() - 1;
                if (extra > 0) result.components[PAWNS].add(-12 * extra, -18 * extra, sign);
            }
        }
        auto p = ctx.pawns[c];
        while (p) {
            const int sq = p.pop(), f = sq % 8, rank = c == 0 ? sq / 8 : 7 - sq / 8;
            const int next = sq + (c == 0 ? 8 : -8);
            const auto adjacent = ctx.pawns[c] & eval_masks::adjacent(f);
            const bool supported = ctx.pawn_attacks[c].check(sq);
            const auto same_rank = chess::Bitboard(0xFFULL << (8 * (sq / 8)));
            if (options.uses(PAWNS)) {
                if (!adjacent) result.components[PAWNS].add(-10, -14, sign);
                if (supported || (adjacent & same_rank)) result.components[PAWNS].add(5, 8, sign);
                // Conservative: a neighbor exists, but all neighbors are ahead;
                // the unsupported pawn must advance onto an enemy pawn attack.
                if (adjacent && !supported && !(adjacent & ~chess::Bitboard(eval_masks::FORWARD[c][sq])) &&
                    !board.occ().check(next) && ctx.pawn_attacks[1 - c].check(next))
                    result.components[PAWNS].add(-8, -10, sign);
            }
            const auto ahead = chess::Bitboard(eval_masks::FORWARD[c][sq]);
            const auto corridor = ahead & (eval_masks::file(f) | eval_masks::adjacent(f));
            if (!(ctx.pawns[1 - c] & corridor) && !(ctx.pawns[c] & ahead & eval_masks::file(f))) {
                ctx.passers[c] |= chess::Bitboard::fromSquare(sq);
                if (options.uses(PASSERS)) {
                    int mg = passed_mg[rank], eg = passed_eg[rank];
                    if (supported) { mg += 8; eg += 15; }
                    if (board.occ() & ahead & eval_masks::file(f)) { mg /= 2; eg /= 2; }
                    result.components[PASSERS].add(mg, eg, sign);
                }
            }
        }
    }
}

void evaluate_bishops_rooks(const chess::Board& board, const EvalContext& ctx, Evaluation& result,
                            const EvaluationOptions& options) {
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        const int sign = c == 0 ? 1 : -1;
        const auto bishops = board.pieces(chess::PieceType::BISHOP, color);
        if (options.uses(BISHOPS) && (bishops & 0x55AA55AA55AA55AAULL) &&
            (bishops & 0xAA55AA55AA55AA55ULL)) result.components[BISHOPS].add(25, 40, sign);
        if (!options.uses(ROOKS)) continue;
        auto rooks = board.pieces(chess::PieceType::ROOK, color);
        while (rooks) {
            const int sq = rooks.pop(), f = sq % 8;
            const auto file = chess::Bitboard(eval_masks::file(f));
            if (!(ctx.pawns[c] & file)) {
                const bool open = !(ctx.pawns[1 - c] & file);
                result.components[ROOKS].add(open ? 18 : 10, open ? 12 : 8, sign);
            }
            const int rank = c == 0 ? sq / 8 : 7 - sq / 8;
            const int enemy_king_rank = c == 0 ? board.kingSq(~color).index() / 8 : 7 - board.kingSq(~color).index() / 8;
            if (rank == 6 && (enemy_king_rank == 7 ||
                (ctx.pawns[1 - c] & (0xFFULL << (8 * (sq / 8))))))
                result.components[ROOKS].add(15, 25, sign);
            // The rook must have an unobstructed line to a passer, from behind
            // relative to that pawn's direction. Credit at most once per rook.
            bool behind = false;
            for (int owner = 0; owner < 2 && !behind; ++owner) {
                auto passers = ctx.passers[owner] & file;
                while (passers) {
                    const int pawn = passers.pop();
                    if ((owner == 0 ? sq < pawn : sq > pawn) &&
                        (chess::attacks::rook(chess::Square(sq), board.occ()) & chess::Bitboard::fromSquare(pawn))) {
                        behind = true;
                        break;
                    }
                }
            }
            if (behind) result.components[ROOKS].add(10, 20, sign);
        }
    }
}

}  // namespace

int taper(EvalScore score, int phase) {
    return interpolate(score.middlegame, score.endgame, std::clamp(phase, 0, MAX_PHASE));
}

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
    evaluate_pst<false>(board, result);
    return result;
}

int evaluate(const chess::Board& board, bool use_pst) {
    // Material-only search retains its original popcount-only fast path.
    return use_pst ? evaluate_breakdown(board, true).total() : evaluate_material(board);
}

template<bool Diagnostics>
Evaluation advanced_breakdown(const chess::Board& board, bool use_pst, const EvaluationOptions& options) {
    if (!options.advanced) return evaluate_breakdown(board, use_pst);
    Evaluation result;
    result.advanced = true;
    result.phase = game_phase(board);
    result.material = evaluate_material(board);
    result.components[MATERIAL] = {result.material, result.material};
    if (use_pst) evaluate_pst<true, Diagnostics>(board, result);
    EvalContext context(board);
    evaluate_pawns(board, context, result, options);
    evaluate_bishops_rooks(board, context, result, options);
    if (options.uses(MOBILITY) || options.uses(KING_SAFETY) || options.uses(SPACE)) build_attacks(board, context);
    evaluate_mobility_outposts(board, context, result, options);
    if (options.uses(KING_SAFETY)) evaluate_king_safety(board, context, result);
    if (options.uses(SPACE)) evaluate_space(board, context, result);
    if (options.uses(ENDGAME)) evaluate_endgame(board, context, result);
    int rounded_sum = 0;
    for (const auto component : result.components) {
        result.sum.add(component.middlegame, component.endgame);
        if constexpr (Diagnostics) rounded_sum += taper(component, result.phase);
    }
    const int blended = taper(result.sum, result.phase);
    if constexpr (Diagnostics) result.rounding = blended - rounded_sum;
    result.score = blended * result.scale / 256;
    result.scaling = result.score - blended;
    return result;
}

Evaluation evaluate_breakdown(const chess::Board& board, bool use_pst, const EvaluationOptions& options) {
    return advanced_breakdown<true>(board, use_pst, options);
}

int evaluate(const chess::Board& board, bool use_pst, const EvaluationOptions& options) {
    return options.advanced ? advanced_breakdown<false>(board, use_pst, options).total() : evaluate(board, use_pst);
}

}  // namespace chesslab
