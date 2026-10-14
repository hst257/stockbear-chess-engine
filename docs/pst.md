# Piece-square evaluation

PSTs add a small positional bonus to each piece's material value. Material alone
cannot distinguish a knight on the edge from one in the center. The engine now
defaults to material plus PSTs; material-only remains selectable for comparisons.
Search algorithms, depth defaults, terminal detection, and move ordering are unchanged.

## Tables and source

All seven complete 64-entry arrays are in [pst.hpp](../engine/src/pst.hpp).
They implement Tomasz Michniewski's classical
[Simplified Evaluation Function](https://chessprogramming.org/Simplified_Evaluation_Function),
adapted from Andrew Healey's MIT-licensed
[Andoma tables](https://github.com/healeycodes/andoma/blob/main/evaluate.py).
The [source notes and full MIT notice](../engine/vendor/andoma/README.md) record
orientation normalization and two corrected king-entry signs.

| Piece/table | Bonus range (cp) | Purpose |
| --- | ---: | --- |
| Pawn | -20 to +50 | Encourage central development and useful advancement; retain shelter-square bonuses |
| Knight | -50 to +20 | Prefer central squares over edges and undeveloped corners |
| Bishop | -20 to +10 | Modest bonuses for active central/diagonal placement |
| Rook | -5 to +10 | Reward seventh-rank activity and useful home-rank central squares |
| Queen | -20 to +5 | Conservative positional preferences; tactical safety still depends on search |
| King middlegame | -50 to +30 | Prefer sheltered/castled squares over central exposure |
| King endgame | -50 to +40 | Prefer active central king placement |

For example, White Nd4 has a +20 cp bonus; Na3 has -30 cp. Both retain the same
320 cp material value, so the central knight scores 50 cp higher with other
factors controlled. This is much smaller than a rook's 500 cp material value.

## Orientation, score, and phase

The vendored rules library uses a1=0, h1=7, a8=56, h8=63, verified by compile-time
assertions. Tables are White-relative, rank 1 first, files a through h. White uses
the square index directly; Black uses `square ^ 56`, flipping ranks without
flipping files. Contributions are added for White and subtracted for Black.
Rank-mirrored, color-swapped positions therefore negate every score component.

Material values remain P=100, N=320, B=330, R=500, Q=900, K=0. They are counted
once. Kings retain search's separate mate handling.

Remaining phase counts both sides' non-pawn pieces: N/B=1, R=2, Q=4; pawns and
kings contribute zero. The initial sum is 24. Clamp to 0–24, including promoted
material. Each king's bonus is:

```text
(king_middlegame[square] * phase + king_endgame[square] * (24 - phase)) / 24
```

Round each king to the nearest centipawn, exact halves away from zero, then
subtract Black's contribution. This symmetric rounding preserves color symmetry.
At phase 24, king safety dominates; at phase 0, centralization dominates. Only
kings taper in this milestone. The evaluation module separates phase and tables
so other pieces can receive endgame tables later if requested.

The evaluator uses compile-time arrays, stack-only accumulators, and occupied-piece
bitboards. It neither copies boards nor allocates memory. Material-only search
keeps its original popcount-based evaluator.

## Enable, disable, and inspect

Press **G**, toggle **PST: on/off**, then Apply to game to preserve the
position, or Start new game. Press **E** for Search lab and toggle **PST: on/off** to preserve the
current board. Old rows clear; rerun Compare position. Both comparison algorithms
use the selected evaluation. Toggles are locked during active searches.

![Evaluation selection](search-setup.png)

```powershell
.\launch.bat --mode engine                   # PST enabled by default
.\launch.bat --mode engine --no-pst          # Material-only baseline
.\launch.bat --mode engine --pst             # Explicitly enable PST
```

UCI exposes `option name UsePST type check default true`. For diagnostics:

```text
setoption name UsePST value true
position startpos moves g1f3
eval
```

The response is one UCI-safe line beginning `info string eval`, followed by JSON:
material, six PST contributions, positional sum, total, phase, and `use_pst`.
Here material=0, knight PST=+50, all other PST contributions=0, total=+50,
phase=24. `setoption name UsePST value false` makes every PST contribution zero.
UCI search scores remain relative to the player to move; diagnostic totals and
GUI scores favor White. `eval` stops outstanding search before reporting.

Standalone JSON diagnostics use the same evaluator as search:

```powershell
.\engine\build\chesslab-engine.exe --eval "7k/8/8/8/3N4/8/8/7K w - - 0 1"
.\engine\build\chesslab-engine.exe --eval --no-pst "7k/8/8/8/3N4/8/8/7K w - - 0 1"
```

Diagnostics show static evaluation, including in drawn or terminal positions.
Search checks mate, stalemate, insufficient material, and other existing draw
conditions before static evaluation; those terminal scores take precedence.

## Verification and benchmarks

```powershell
.\build_engine.bat
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.benchmark_evaluation --depth 5 --repeats 3 --match-games 4 --output artifacts\pst-benchmark.json
```

**557 tests pass in the current full suite on Windows.** PST checks cover all six piece types, asymmetric
rank orientation, color symmetry, all 25 phase values, rounding, promotion-phase
clamping, no material double-counting, terminal precedence, UCI diagnostics,
search-leaf/diagnostic agreement, Minimax/alpha-beta equivalence, interruption,
GUI settings, and the exact old material-only node baselines.

The [recorded benchmark](pst-benchmark.json) contains all FENs, raw samples,
engine hash, CPU/OS, and limits. Same machine, single worker, alpha-beta,
iterative deepening and ordering enabled, depth 5, 15-second cap per search,
three repeats with mode order alternated. Rows select the median wall-time run.
The recorded PST benchmark predates transposition caching; the reproduction tool
explicitly disables TT, quiescence, and PVS to retain those baseline conditions. For cache comparisons,
see [transposition tables](transposition-tables.md).

| Position | PST | Move | White score (cp) | Nodes | Engine seconds | Engine NPS |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Initial | Off | b3 | +100 | 25,261 | 0.002 | 12,630,500 |
| Initial | On | e4 | +70 | 182,596 | 0.020 | 9,129,800 |
| Kiwipete | Off | Bxa6 | +230 | 84,750 | 0.011 | 7,704,545 |
| Kiwipete | On | dxe6 | +315 | 87,554 | 0.013 | 6,734,923 |
| Pawn ending | Off | Kc3 | 0 | 1,941 | 0.000 | 1,941,000 |
| Pawn ending | On | Ke5 | +65 | 2,056 | 0.000 | 2,056,000 |

PST changes scores and cutoffs and can increase the search tree, as in the opening.
Scores from different evaluators are not interchangeable strength measurements.
NPS/time use the engine's coarse millisecond clock; sub-millisecond times round
down and NPS divides by at least 1 ms. These short timings are noisy. Raw JSON
also records high-resolution wall time, including UCI overhead.

Four smoke games alternate colors from the initial position and a six-ply Italian
opening, depth 3, identical 15-second caps, at most 160 additional plies. Available
draws are claimed; games hitting the cap would be marked unfinished, not draws.
PST scored **2 wins, 1 draw, 1 loss**; none were unfinished. Full games are in
[pst-benchmark.pgn](pst-benchmark.pgn). This tiny sample does not establish an Elo
improvement, and node counts/speed alone do not measure playing strength.

## Limitations

Classical fixed tables supply square preferences, not board-context understanding.
They do not detect pawn structure, open files, mobility, attacked queens, or actual
pawn shelter. King safety is only a square-and-phase approximation. Material-only
remains intentionally weak. Quiescence and PVS are available separately from PST; see the [search guide](search.md).
Opening books, NNUE, incremental evaluation, and an evaluation cache remain deferred.
Further evaluation or search changes require a new request.
