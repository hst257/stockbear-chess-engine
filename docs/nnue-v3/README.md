# King-relative NNUE v3 study

The [final research report](../../NNUE_V3_KING_RELATIVE_REPORT.md) records the
completed implementation and exactly 20 games: v3 scored 3 wins, 8 draws and
9 losses against optimized v2. Optimized v2 remains the preferred NNUE;
classical remains the default. The conditional classical match was not justified.

Start with [the design](../../NNUE_V3_DESIGN.md). All prior models, data and
research are retained. The frozen optimized-v2 baseline is revision `2432323`,
tag `nnue-v3-baseline-2432323`. Classical and v2 source/model identity and exact
deterministic parity are independent gates. V3 changes no search policy.

## Models and selection

`engine/networks/v3/stockbear-v3-a.sbnnue` uses full 64-square conditioning.
Candidate B uses 16 king buckets with the same 32/16 head and training settings.
Validation selects B, aliased by `stockbear-v3-selected.sbnnue`; this does not
imply a chess-strength improvement. Classical stays the application default.
The [format](MODEL_FORMAT.md) uses explicit versioned feature/architecture IDs.

The ordinary `nnue` option uses the network embedded in the chosen executable.
For the three-way study and GUI selection of **optimized v2** versus v3, use
the v3 release executable, which embeds the frozen Compact v2 model:

```powershell
.\.venv\Scripts\python.exe -m app.main --engine artifacts/nnue-v3/release/engine.exe --mode engine --evaluator nnue_v3
# --evaluator nnue selects its embedded optimized v2; classical is the default.
```

UCI supports `Evaluator=classical|nnue|nnue_v3` and the string option
`NNUEV3File` (use an absolute path outside the repository). The GUI cycles the
three choices and labels v3 experimental. `NNUEIncremental=false` is the full
refresh oracle. V3 is scalar float32; v2 kernel controls retain their v2 meaning.
The ordinary application executable retains its original embedded v1 model;
no existing model default is silently migrated.

## Data and training

Read-only v2 data reuse retains 999,464 training / 19,930 validation / 20,152
test examples. Targets, ordinal rows, grouped partitions and teacher labels are
unchanged. New uint16 caches live under `StockBear_NNUE_training/data/v3/`.
Checkpoints/optimizer/RNG states live under its `runs/v3/`; no files are removed.
Source FEN, cross-language, resource-pilot and parity gates precede full runs.

```powershell
# From StockBear_NNUE_training; use its existing CUDA environment.
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m stockbear.v3.train pilot --king-buckets 16
.\.venv\Scripts\python.exe -m stockbear.v3.train full --king-buckets 16
```

Completed experiment signatures are immutable and include source hashes. Changed
code must not be used to resume or overwrite them. Exact A/B training sources
are preserved under `StockBear_NNUE_training/reports/v3/source-a|source-b/`,
including the pre-hardening export validators used during training. Reproduce
training in a separate checkout using that snapshot and the identical runtime,
prepared data and seed; preserve existing checkpoints and choose fresh run/cache
directories for new experiments. The current stricter export validator changes
no predictions or stored model bytes. Final test evaluation follows recorded
validation selection; it is never used for tuning.

## Verification and measurement

Build before testing. Typical repository-root commands:

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py --nnue-model engine/networks/v2/stockbear-v2-compact.sbnnue --output artifacts/nnue-v3/release/engine.exe
.\.venv\Scripts\python.exe tools/build_engine.py --target v3-tests --nnue-model engine/networks/v2/stockbear-v2-compact.sbnnue --output artifacts/nnue-v3/release/probe.exe
StockBear_NNUE_training\.venv\Scripts\python.exe -m tools.verify_nnue_v3 --model engine/networks/v3/stockbear-v3-selected.sbnnue --probe artifacts/nnue-v3/release/probe.exe --heldout --positions 20152 --output NEW-parity.json
.\.venv\Scripts\python.exe -m tools.verify_nnue_v3_search --engine artifacts/nnue-v3/release/engine.exe --output NEW-search-parity.json --full
.\.venv\Scripts\python.exe -m tools.run_nnue_v3_experiments
```

Only one heavy experiment runs at a time. Release measurements use rotated
trials, Hash16, one worker and fresh TT states. Instrumented scopes are separate;
their percentages are not release runtime shares. Raw records retain short mates
and excluded timing cases. CPU accounting is relative to one logical CPU.

The user reduced matches **before play** to **20 games / 10 opening pairs at
500ms**, with the smoke pair included. The conditional classical cohort is also
20 games. No automatic extension. Capped games stay unfinished, never draws.
Use paired uncertainty; compare the corresponding first 10 opening pairs when
referring to the earlier 40-game v2/classical cohort. Full older results remain
separate from matched-subset descriptions. State/checkpoints and native build
logs remain under `artifacts/nnue-v3/`; final evidence is retained in this folder.
