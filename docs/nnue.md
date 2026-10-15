# Experimental StockBear NNUE integration

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
through siblings, undo, re-search and cancellation. Child feature sets are
extracted from the board for clear special-move correctness; sums are incremental.

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
