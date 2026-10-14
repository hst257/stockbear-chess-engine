# Advanced classical evaluation

ChessLab 0.10 adds modular handcrafted evaluation to the existing C++ engine.
Advanced evaluation defaults to on. Search algorithms, draw adjudication, GUI
layout, and the default 1-second thinking budget are unchanged. There is no NNUE,
opening book, tablebase, evaluation cache, or new pruning algorithm.

## Implementation map

- `engine/src/evaluation.hpp`: score pairs, category switches, breakdown contract.
- `engine/src/evaluation.cpp`: shared PST walk and separate feature functions.
- `engine/src/evaluation_masks.hpp`: compile-time files, forward corridors, center masks.
- `engine/src/main.cpp`: UCI selection, JSON diagnostics, native CPU profiling.
- `engine/src/search.hpp` / `search.cpp`: snapshot options and pass them to existing evaluation calls.
- `app/engine_client.py` / `main.py`: frozen selection, recorded stats, launcher flag.
- `tests/test_advanced_evaluation.py`: component and real-engine contracts; older fixtures explicitly retain baseline mode.
- `tools/profile_evaluation.py`, `benchmark_advanced_evaluation.py`, `match_optimizations.py`: profiling, matched searches, reused game harness. Older tools explicitly select their historical evaluation.

## Score convention and taper

Every component accumulates **White minus Black** middlegame (MG) and endgame
(EG) centipawns. The engine uses maximizing/minimizing Minimax, not Negamax;
UCI converts the score to the player-to-move perspective. GUI scores favor White.
Black PST indexes use `square ^ 56`, reversing ranks without reversing files.
Relative rank below means rank 1–8 from that pawn's own side.

Phase is the sum of remaining N/B=1, R=2, Q=4 for both sides, clamped to 0–24.
Pawns and kings have phase weight zero. The initial position has phase 24.

```text
MG = sum(component MG); EG = sum(component EG)
blended = round_away_at_halves((MG * phase + EG * (24 - phase)) / 24)
total = truncate_toward_zero(blended * scale / 256)
```

The advanced evaluator blends once, including the raw king tables. It never
tapers a previously tapered king score or counts material twice. Larger pawn,
rook, and king-proximity EG weights reflect their importance after exchanges;
king attack penalties are MG-only. No tempo bonus is used: changing the side to
move alone does not change static evaluation. Mate, stalemate, repetition,
fifty-move, and insufficient-material results take precedence in search.

The exact historical baseline remains available. It retains per-king rounding,
so switching off every advanced category can differ from that baseline by 1 cp
at intermediate phases. Use the master switch for exact historical reproduction.

## Components and weights

All numbers are centipawns. These are conservative initial weights, not fitted
parameters or evidence of an Elo improvement.

| Component | MG / EG weights and definition |
| --- | --- |
| Material | P=100, N=320, B=330, R=500, Q=900; identical MG/EG. Kings have no material value. |
| PST | Existing attributed Andoma tables, unchanged. Non-king tables serve both phases; the existing king MG/EG arrays enter the single blend. See [PST tables and attribution](pst.md). |
| Doubled pawns | −12 / −18 per extra friendly pawn on a file. |
| Isolated pawns | −10 / −14 per pawn with no friendly pawn anywhere on adjacent files. |
| Backward pawns | −8 / −10 if unsupported, adjacent friendly pawns exist but are all ahead, and the empty forward square is attacked by an enemy pawn. This intentionally misses uncertain cases. |
| Connected pawns | +5 / +8 per pawn supported by a friendly pawn or having a same-rank neighbor; credited once per pawn. |
| Passed pawns | Relative ranks 2–7: MG `[0,5,12,22,38,65]`, EG `[0,10,24,45,80,130]`. No opposing pawn ahead on the same/adjacent files, and no friendly pawn ahead on the same file. Only the leading pawn in a doubled file qualifies. |
| Protected/blocked passers | Add +8 / +15 if pawn-supported. Halve the resulting bonus, with integer truncation, if any occupied square lies ahead on its file. No immediate-promotion assumption. |
| Bishop pair | +25 / +40 for bishops on both square colors, once per side. Two promoted bishops of the same color do not qualify. |
| Rook files | Open +18 / +12; semi-open +10 / +8. Any friendly pawn excludes both; an enemy pawn distinguishes semi-open from open. |
| Rook seventh rank | +15 / +25 when the enemy king is on its home rank or enemy pawns occupy the rook's rank. |
| Rook behind passer | +10 / +20, once per rook, behind either side's passer relative to that pawn's direction; requires an unobstructed rook attack to the pawn. |
| Mobility | N/B/R/Q distinct safe destinations per piece type, minus neutral counts `4/6/7/12` per piece. Multiply by MG `3/3/2/1`, EG `3/4/3/1`. Shared destinations count once, discouraging redundant coverage. |
| Knight outposts | +18 / +12 on relative ranks 4–6 and files b–g, pawn-supported, with no enemy pawn ahead on an adjacent file that could challenge the square. No bishop outpost bonus. |
| Space/center | +2 / +1 per safely controlled d4/e4/d5/e5 square. MG +1 per safe, empty, pawn-controlled square on c4–f6 (White) or c3–f5 (Black). MG +3 per supported central pawn on relative ranks 4–6, files c–f, not under enemy attack. |
| Endgame king activity | EG `2 * sum(7 − Chebyshev distance to each enemy pawn) / enemy pawn count`, truncated per side. No extra generic centralization bonus: king PST already supplies it. |
| King/passer proximity | EG `2 * max(1, relative_rank − 2) * (enemy king distance − friendly king distance)` to each passer's next square. This rewards local king support; it does not solve promotion races. |

Mobility removes friendly occupancy and squares attacked by enemy pawns or the
enemy king. Other enemy-controlled squares need a second friendly attacker:
the moving piece's own attack on its destination is not counted as a defender.
Attack maps include pinned pieces and are approximate; no legal move generation,
board copying, or make/unmake occurs inside evaluation.

Safe center control excludes enemy pawn attacks and other enemy-controlled
squares unless friendly pawns defend them. Territorial credit requires friendly
pawn control and an empty square. Space rewards control rather than assigning
another large bonus for occupying a central PST square.

### King safety formula

For each king, inspect its own file and adjacent files (two files at an edge).
Add shelter penalties per file: 0 for a pawn one rank ahead, 5 for a pawn two
ranks ahead, otherwise 12. If no friendly pawn exists on that file, add 8 when
an enemy pawn exists, otherwise 12.

The zone is the king square plus adjacent squares. Each enemy N/B/R/Q touching
it counts as one attacker. Its attack units are `min(zone squares hit,3)` times
N=2/B=2/R=3/Q=5. Add:

```text
2 * sum(attack units) * min(number of attackers, 4)
+ 2 * zone squares attacked by enemy pawns
+ 3 * zone squares attacked by enemy rooks/queens and not pawn-defended
```

Multiply the complete penalty by `min(enemy phase material,12)/12`, truncating
the nonnegative penalty, then subtract it from the king's MG score. EG is zero.
The global phase blend reduces it further in endings. A pawn-only enemy gives
no safety penalty. Friendly pieces cannot become enemy attackers. Castling
rights, castling history, and assumptions that castling is always best are absent.

### Material scaling

Default scale is 256/256. With no rooks or queens, use 128/256 for pawnless
positions with at most one minor per side. Use 192/256 when each side has exactly
one bishop, they have opposite square colors, no knights exist, and at most four
pawns remain. Other material patterns retain full scale. Disabling `EvalEndgame`
disables both its additive scores and scaling. These rules soften drawish scores;
they do not adjudicate draws. Winning two-bishop/B+N material is not scaled away.

## Selection and diagnostics

```powershell
.\launch.bat --mode engine                           # advanced, 1-second default
.\launch.bat --mode engine --no-advanced-evaluation  # exact material/PST baseline
.\launch.bat --mode engine --no-advanced-evaluation --no-pst # material only
.\engine\build\chesslab-engine.exe --eval "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1"
.\engine\build\chesslab-engine.exe --eval --baseline "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1"
.\engine\build\chesslab-engine.exe --eval --disable EvalMobility "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1"
```

`UseAdvancedEvaluation` defaults to true. Independent UCI check options also
default true: `EvalPawns`, `EvalPassers`, `EvalBishopPair`, `EvalRooks`,
`EvalMobility`, `EvalOutposts`, `EvalKingSafety`, `EvalSpace`, `EvalEndgame`.
The master switch ignores their values when off. `UsePST` independently controls
only PSTs; turning it off alone leaves advanced terms enabled. No new controls
were added to the main GUI. Python's frozen `EngineSettings` snapshots the master
selection for both comparison algorithms and records it in `SearchStats`.

```text
uci
setoption name UseAdvancedEvaluation value true
setoption name EvalMobility value false
position startpos moves e2e4 e7e5
eval
```

`eval` stops any outstanding search and emits one `info string eval {JSON}`
line. Each `components` entry contains `mg`, `eg`, and phase-tapered `cp`.
Top-level `mg`/`eg` are the raw sums. Independent component rounding can differ
from rounding the global sum, so diagnostics explicitly report `rounding`.
`scaling` is the final scaling change in cp; `scale` is its numerator over 256.

```text
total = sum(components[*].cp) + rounding + scaling
```

Legacy `material`, per-piece `pst`, and `positional` fields remain available;
`positional` means the sum of the six independently tapered PST entries, not
the complete advanced positional score. Use the component reconciliation above
for advanced mode. Static diagnostics can be nonzero in terminal/insufficient
positions; search first applies the existing terminal rules. Search, Q stand-pat,
and the existing null-move static guard all receive the same selected evaluator.
TT state starts fresh per search, so changing evaluation cannot reuse old scores.

## Verification and reproduction

Implementation followed the requested order. Each stage ran the accumulated
evaluation tests before the next stage. Passing counts: 89 modular/taper,
100 pawns, 102 bishop/rook, 108 mobility/outposts, 110 king safety, 111 space,
124 endgame. Corresponding profiles and executable hashes are retained in
[`evaluation-stages/`](evaluation-stages/). Stage 8 also fixes self-defense in
mobility and removes diagnostic-only rounding from search calls.

The final Windows suite passes **852 tests**, including baseline regression,
all phases, mirror/sign symmetry, exact component reconciliation, category
switches, legal PVs, PVS/full-window/cache equivalence, mode changes, cancellation,
and insufficient draws. Native tests are included in that suite. The native
desktop check played e4, observed a legal ...Nc6 reply at 1 second, and completed
both Search lab comparisons without moving the board during comparison.

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.profile_evaluation --stage local --ablation --repeats 1000000 --output artifacts\evaluation-profile.json
.\.venv\Scripts\python.exe -m tools.benchmark_advanced_evaluation --depth 5 --times 100 500 1000 --repeats 3 --output artifacts\evaluation-benchmark.json
.\.venv\Scripts\python.exe -m tools.match_optimizations --comparison evaluation --games 8 --movetime 100 --max-plies 160 --output artifacts\evaluation-matches.json
```

Profiling repeatedly calls the compiled evaluator in one process, excluding
startup/JSON overhead. Each cell reports the median of three samples, one million
calls per sample. Final opening/middlegame costs are about **187 ns** advanced
versus **33–35 ns** baseline; the pawn endgame is **66 ns** versus **12 ns**.
Disabling pawn structure saves about 26–27 ns and disabling endgame activity
about 28–29 ns in the measured opening/middlegame. Costs are not additive because
categories share context. Tiny negative savings in ablations are measurement
noise. No cache was added: the pawn work is bounded and cheap in absolute terms;
a pawn cache needs an independent hit-rate and memory-cost experiment.

## Recorded search comparison

[Raw benchmark JSON](advanced-evaluation-benchmark.json) contains 56 cells and
168 searches: seven positions, baseline/advanced, depth 5 and 100/500/1000 ms,
three alternating-order samples. Tables select the sample nearest median wall
time; when wall times tie, the first such sample is retained. Depth, nodes, NPS,
engine/wall time, White score, best move, legal PV, all samples, configuration,
and executable SHA-256 are included. Windows Python 3.11/Zig 0.13, C++17 `-O2`;
results are machine/session-specific, especially millisecond-scale depth tests.
Both modes use identical current search settings, including Q/PVS/TT and
aspiration/NMP/LMR. Only the evaluation master flag changes.

| Depth 5 position | Mode | Move / White cp | Nodes | NPS | Engine seconds |
| --- | --- | --- | ---: | ---: | ---: |
| Opening | Baseline | Nc3 / +40 | 10,405 | 3,468,333 | .003 |
| Opening | Advanced | Nc3 / +49 | 11,282 | 2,256,400 | .005 |
| Middlegame | Baseline | Bg5 / +10 | 88,463 | 4,212,523 | .021 |
| Middlegame | Advanced | a3 / +6 | 143,052 | 2,307,290 | .062 |
| Tactical (Kiwipete) | Baseline | dxe6 / +40 | 355,317 | 4,737,560 | .075 |
| Tactical (Kiwipete) | Advanced | dxe6 / +35 | 273,742 | 2,558,336 | .107 |
| Pawn endgame | Baseline | Ke5 / +65 | 1,987 | 993,500 | .002 |
| Pawn endgame | Advanced | Ke5 / +79 | 2,243 | 1,121,500 | .002 |

| 1-second position | Baseline depth / nodes / move / cp | Advanced depth / nodes / move / cp |
| --- | --- | --- |
| Opening | 9 / 3,955,712 / e4 / +25 | 8 / 1,826,048 / Nc3 / +14 |
| Middlegame | 8 / 3,179,520 / Be3 / +5 | 7 / 1,707,776 / Na4 / +24 |
| Tactical | 7 / 3,470,080 / dxe6 / +30 | 7 / 1,678,592 / dxe6 / +28 |
| Pawn endgame | 13 / 5,346,048 / Ke5 / +70 | 12 / 4,113,408 / Ke5 / +60 |
| Pawn zugzwang | 16 / 4,917,760 / Ke5 / +190 | 14 / 4,810,240 / Kc5 / +231 |

At exactly 1 engine second, nodes also equal reported NPS. The richer evaluator
reduces throughput by about 46�54% in the measured opening/middlegame/tactical
samples. A smaller tree can still take longer: tactical depth-5 nodes fall 23%,
but engine time rises from 75 to 107 ms. Endgame timing is less dominated by
feature evaluation. Both modes find Qg7# and return the same terminal draw;
fixed-time terminal/mate searches finish early rather than waiting out the clock.
Differences between score values are not measurements of move quality.

### Color-balanced smoke games

[Match JSON](advanced-evaluation-matches.json) and [replayable PGNs](advanced-evaluation-matches.pgn)
record eight 100-ms games, paired colors for initial, Italian, Queen's Gambit,
and Sicilian starting sequences through the existing match harness. Both sides
use search stage 3; the evaluation flag alone changes per side. The advanced
side scored **2 wins, 1 loss, 5 draws**, with no unfinished games. Three decisive
games ended in checkmate; the draws used threefold claims. The maximum was 160
additional plies. Every selected move was checked for legality; JSON records each
move's completed depth, nodes, and time. This is a smoke sample, not an Elo
estimate or proof that every feature helps. No feature showed a reproducible
correctness failure or clear harm sufficient to disable it by default.

## Limitations and next tuning work

Weights have not been statistically tuned. Pseudo-attacks overestimate pinned
pieces; double-control approximates safety without SEE. Union mobility can
discount coordinated pieces. Backward-pawn detection is deliberately incomplete.
Passer bonuses do not solve races, rook activity omits connectivity, outposts do
not test exchange availability, and king zones omit x-rays/checking sequences.
King activity has no opposition/tempo solver. Drawish scaling can undervalue
winning opposite-bishop positions. The evaluator is deterministic and symmetric,
but evaluation scores are estimates, not outcome probabilities.

Future work should tune weights against a held-out labeled position set, then
run substantially larger color-balanced games at multiple budgets. Evaluate
king-safety, mobility, and scaling ablations separately; profile real search
positions before considering pawn hashing. Any incremental evaluation, cache,
specialized endgame logic, or further search changes needs a separate request.
