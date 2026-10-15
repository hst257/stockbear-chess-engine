# Experimental StockBear NNUE integration

The [v2 optimization report](../NNUE_V2_OPTIMIZATION_RESULTS.md) covers the newer
finalists, native kernels and new controlled matches. The measurements below
remain the frozen v1 integration results.

ChessLab 0.13 supports the existing classical evaluator and the trained compact
StockBear NNUE. **Classical remains the default.** Both run inside the native
engine; Python/PyTorch never supplies evaluations or moves during play.

## Choose an evaluator

Open game setup (**G**) or Search lab (**E**) and click **Eval: Classical/NNUE**.
Apply settings to preserve the game or start a new game. Applying a different
evaluator cancels the old request; Search lab permits switching while idle.
The sidebar identifies the evaluator. PST is marked **classical only** under NNUE.

```powershell
.\build_engine.bat
.\launch.bat --mode engine --evaluator nnue
.\launch.bat --mode engine --evaluator classical
```

UCI: `setoption name Evaluator value nnue` or `classical`.
`NNUEIncremental` defaults true; false rebuilds accumulators at each evaluation
for verification. Classical category/PST/weight switches do not affect NNUE.
There is no material/PST blend or handcrafted correction. All search settings
and time budgets otherwise remain identical.

## Model and deployment

The validation-selected model is
`StockBear_NNUE_training/exports/stockbear-compact.sbnnue`: width 32, hidden 16,
26,081 parameters, 105,484 bytes. Its full-file SHA256 is
`47076595f00d6218ad8b7d6085da688bde43459d14571e2d456ceba436b1e512`.
Exact weights, 128 golden positions, metadata and match presets are bundled in
`engine/networks`. See the original [selection](../StockBear_NNUE_training/reports/selection.json)
and [export contract](../StockBear_NNUE_training/docs/EXPORT_SPEC.md).

This is **StockBear float32 v1**, not a Stockfish `.nnue`. The build validates
magic, feature/activation/score conventions, dimensions, tensor names/shapes/
offsets, finite values, zero padding, payload size and SHA256. Exact hexadecimal
float constants are generated in an ignored header and embedded in the binary.
Runtime inference requires no model path, Torch, NumPy, ONNX or GPU.

Another compatible export can be embedded explicitly:

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py --nnue-model PATH\model.sbnnue
```

Width <=256 and hidden <=128 are supported with the same features. Arbitrary
runtime model loading is not implemented. Preserve the bundled model/goldens
when experimenting with another network. Build metadata records model identity.

## Native inference and state

Each perspective has 780 piece/castling/legal-EP features, with Black rank
mirroring. Extraction matches python-chess castling rights and legal EP,
including pinned EP rejection. Unclipped accumulators stay in fixed White/Black
order. Every search refreshes its root; real/null children copy the parent sums,
subtract removed rows and add new ones. A private stack preserves parent state
through siblings, undo, re-search and cancellation. Current builds derive piece
deltas before the move and check rights/legal-EP afterward; `NNUEKernel=reference`
retains the original board-extracted path for verification.

Inference clips side-to-move/opponent accumulators, applies the clipped hidden
layer and scalar output, multiplies by 400, then converts to White's perspective
and rounds to centipawns. Static values cannot enter the mate-score band.
Mate/stalemate, repetition, fifty-move claims and insufficient material retain
priority over NNUE. The model itself has no draw-history features.

Weights are immutable and state is search-local. Option changes join the
worker; fresh per-search TT storage prevents cross-evaluator score reuse.
The classical pawn cache is omitted in NNUE mode. Floating contraction is
disabled; small accumulation differences remain possible.

## Validation and matches

All **128 training golden outputs** match natively; maximum absolute difference
is **0.000107 cp**, below the 0.01 cp contract. Tests cover independent features/
forward math, malformed exports, incremental/rebuilt search, switching, terminal
precedence and GUI request snapshots. The native randomized audit compares
accumulators through ordinary moves, captures, promotions, castling, EP, rights
changes and nulls while checking complete board restoration.

Run paired games with fresh output paths:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\engine\build\chesslab-engine.exe --eval --nnue "FEN"
.\.venv\Scripts\python.exe -m tools.match_optimizations --comparison versions --engine engine/build/chesslab-engine.exe --opponent engine/build/chesslab-engine.exe --candidate-options engine/networks/nnue-options.json --opponent-options engine/networks/classical-options.json --games 100 --movetime 25 --max-plies 240 --output artifacts/nnue/matches.json
```

NNUE is the candidate; classical has advanced evaluation/PST enabled. Both use
the same binary, search defaults, hash, move budget and paired openings with
reversed colors. PGNs name each evaluator. Records include binary hashes,
embedded-model metadata, overrides, moves and depth/time/nodes. Caps remain
unfinished, not draws. Opening filtering uses classical depth-3 scores, so this
is a heuristic screen rather than an evaluator-neutral tournament. Hardware,
time control and uncertainty must accompany strength conclusions; training loss
alone is not Elo.

## Measured results

**This experimental NNUE is weaker than classical at both tested time controls.**
The fixed schedules completed without crashes or unfinished caps:

| Budget per move | Games / opening pairs | NNUE wins | Draws | NNUE losses | NNUE score |
| --- | ---: | ---: | ---: | ---: | ---: |
| 25 ms | 100 / 50 | 1 | 12 | 87 | 7.00% |
| 100 ms | 40 / 20 | 2 | 7 | 31 | 13.75% |

Records: [25 ms JSON](nnue/matches-25ms.json), [PGN](nnue/matches-25ms.pgn);
[100 ms JSON](nnue/matches-100ms.json), [PGN](nnue/matches-100ms.pgn).
Seeds are 20261017 and 20261018. Both cap games after 240 additional plies and
take python-chess draw claims consistently. Schedules were fixed before play;
there was no early stopping based on significance.

The logistic relative-rating point estimates are approximately -449 and -319
Elo for these particular experiments. Conservative paired 95% Hoeffding score
bounds are [0, 26.21%] and [0, 44.12%]; corresponding rating upper endpoints are
about -180 and -41 Elo, with unbounded lower tails. These are nominal bounds
under independent-opening-pair assumptions, not universal Elo ratings. The
four related opening families, classical opening filter, laptop scheduling,
single-thread search and fast time controls limit generalization. Results
support retaining classical as the default; NNUE stays optional.

The [three-repeat alternating search benchmark](nnue/search-benchmark.json)
uses the same portable O2 binary. At 1 second:

| Position | Classical depth / NPS | NNUE depth / NPS |
| --- | ---: | ---: |
| Opening | 10 / 2.93M | 9 / 1.23M |
| Middlegame | 8 / 3.02M | 8 / 1.36M |
| Tactical | 8 / 2.78M | 7 / 1.26M |
| Pawn ending | 13 / 6.47M | 11 / 2.75M |
| Zugzwang fixture | 20 / 6.41M | 18 / 3.14M |

NNUE handles roughly 40–50% of classical's nodes per second in these timed
positions, often completing 1–2 fewer nominal plies. Different evaluation
scores produce different selective trees, so this is search throughput rather
than an isolated forward-pass microbenchmark. The games combine evaluation
quality, CPU cost and interaction with existing search margins; they do not
isolate those causes or establish the strength of larger/future NNUE models.

Both modes used executable SHA256
`5be9d34603f10029a85ac2cd5dbf0d532ba1847ac52d928dd527e1c183495bad`,
with the native implementation committed as `8c3c911`. No native or model
changes were made between the two match sets. Later changes concern Python
status clearing, deeper tests and verification/reporting tools.

All **140 games / 12,790 legal plies** were independently replayed, with PGN
move agreement, paired colors, outcomes, summaries and binary hashes checked.
See [replay verification](nnue/replay-verification.json) and
[golden parity](nnue/parity.json). The NNUE GUI also passed all five time
presets, comparison, undo/new cancellation and six clean worker exits;
[GUI evidence](nnue/gui-verification.json) records the results. A real desktop
launch played legal White d4 with NNUE selected and rendered correctly.

The final complete suite passes **1,120 tests** (78.68 seconds). The UBSan
native audit passed **27,509** randomized real/null state transitions and
incremental/rebuilt comparisons, plus all legal special-move roots, with no
sanitizer findings. See [final verification](nnue/verification.json).

```powershell
.\.venv\Scripts\python.exe -m tools.benchmark_nnue --output artifacts/nnue/local-benchmark.json
.\.venv\Scripts\python.exe -m tools.verify_match_records docs/nnue/matches-25ms.json docs/nnue/matches-100ms.json --check-binaries --output artifacts/nnue/local-replay.json
.\.venv\Scripts\python.exe -m tools.verify_gui_engine --evaluator nnue --output artifacts/nnue/local-gui
```

Binary hash verification requires the frozen match build; omit
`--check-binaries` to replay archived games after building a different engine.
