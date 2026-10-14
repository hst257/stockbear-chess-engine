#pragma once

#include <array>

#include "chess.hpp"

namespace chesslab {

inline constexpr std::array<int, 7> PIECE_VALUES = {100, 320, 330, 500, 900, 0, 0};
inline constexpr std::array<int, 6> PHASE_WEIGHTS = {0, 1, 1, 2, 4, 0};
inline constexpr int MAX_PHASE = 24;

struct EvalScore {
    int middlegame = 0;
    int endgame = 0;
    void add(int mg, int eg, int sign = 1) { middlegame += sign * mg; endgame += sign * eg; }
};

enum EvalComponent { MATERIAL, PST, PAWNS, PASSERS, BISHOPS, ROOKS, MOBILITY,
                     OUTPOSTS, KING_SAFETY, SPACE, ENDGAME, COMPONENT_COUNT };
inline constexpr std::array<const char*, COMPONENT_COUNT> COMPONENT_NAMES = {
    "material", "pst", "pawn_structure", "passed_pawns", "bishop_pair", "rook_activity",
    "mobility", "outposts", "king_safety", "space", "endgame"};
inline constexpr std::array<const char*, COMPONENT_COUNT - 2> EVAL_OPTION_NAMES = {
    "EvalPawns", "EvalPassers", "EvalBishopPair", "EvalRooks", "EvalMobility",
    "EvalOutposts", "EvalKingSafety", "EvalSpace", "EvalEndgame"};

struct EvaluationOptions {
    bool advanced = true;
    std::array<bool, COMPONENT_COUNT - 2> enabled = {true, true, true, true, true, true, true, true, true};
    bool uses(EvalComponent component) const { return enabled[component - 2]; }
};

int taper(EvalScore score, int phase);

struct Evaluation {
    int material = 0;
    std::array<int, 6> pst{};  // White minus Black, indexed by PieceType.
    int phase = 0;
    bool advanced = false;
    std::array<EvalScore, COMPONENT_COUNT> components{};
    EvalScore sum{};
    int scale = 256;
    int rounding = 0;
    int scaling = 0;
    int score = 0;

    int positional() const;
    int total() const { return advanced ? score : material + positional(); }
};

int evaluate_material(const chess::Board& board);
int game_phase(const chess::Board& board);
Evaluation evaluate_breakdown(const chess::Board& board, bool use_pst = true);
int evaluate(const chess::Board& board, bool use_pst = true);
Evaluation evaluate_breakdown(const chess::Board& board, bool use_pst, const EvaluationOptions& options);
int evaluate(const chess::Board& board, bool use_pst, const EvaluationOptions& options);

}  // namespace chesslab
