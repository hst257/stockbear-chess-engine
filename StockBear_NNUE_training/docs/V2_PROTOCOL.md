# StockBear NNUE v2 protocol

This plan was fixed before the full v2 training experiments. The pilot only
checks execution, recovery and serialization. The training target and feature
contract remain those of v1; see `EXPORT_SPEC.md`.

## Data and teacher

The streaming inventory covers all 67 local PGN/zstd archives, not only the
original June–September subset. Source hashes identify the exact inputs.
Selected completed standard games contribute at most 16 sampled positions,
with a minimum three-ply spacing. Game aliases with identical complete mainlines
are merged. Exact canonical positions appear once globally. Known v1 game
partitions are anchored; v1 training positions cannot enter v2 holdouts.

Nested prefixes use deterministic proportional strata over source year, phase,
heuristic tactical category and split. Nominal sizes include all partitions.
Training counts are therefore approximately 80% of nominal size. The fixed
validation and test cohorts come from the first 200,000 positions. Additional
held-out positions remain reserved at every larger prefix. Test tensors may be
prepared and stored, but are not forwarded through a model before selection.

The teacher retains the v1 binary, score perspective and 16,384-node settings.
Six independent one-thread workers were selected by an actual 4/6-worker
benchmark. A single new-game reset is semantically equivalent to the redundant
v1 reset pair; 64 cached comparisons matched scores, mates, depths and nodes.
The original cache is read-only input to the separate v2 cache. Every committed
batch advances a resumable ordinal cursor. A separate 65,536-node check uses
384 representatives and does not silently replace training labels.

## Bounded experiments

| Stage | Dataset | Architectures | Settings |
|---|---:|---|---|
| Pilot | 4,096 | compact | 20 epochs maximum; explicit interruption/resume |
| A | 200K / 500K / 1M | compact 32/16 | same base training settings |
| B | 500K | compact, small 64/32, medium 128/32, large 256/64 | same data and epoch cap; width-scaled learning rate |
| C | 1.25M | two best B architectures | two settings each, then repeat chosen setting with seed + 1 |

The practical largest size comes from the common pool, measured labeling rate,
disk/RAM/GPU audit and a six-hour labeling bound. It is 1.25 million nominal
positions for this execution. There is no open-ended search.

Base settings: AdamW, 60-epoch cap, batch 2,048, learning rate 0.0015, weight decay
0.05, gradient norm cap 1, validation LR reduction after two stagnant epochs,
early stopping after eight, minimum improvement 0.00001. Stage B scales learning
rate by `min(1, sqrt(64 / accumulator_width))`. Stage C compares that rate and
weight decay 0.05 against half that rate and weight decay 0.1. The selected
variant is repeated with a second seed. Float32 CUDA uses deterministic seeds
and disables TF32. No AMP, dropout or BatchNorm is enabled.

Epoch selection and all tuning use validation blended MSE. Architecture
selection uses the mean of the two validation losses for its chosen variant.
The primary seed is exported, regardless of which seed has a lower loss. The
immutable `selection.json` is saved before any final test evaluation. The test
then measures the two finalists and the unchanged v1 checkpoint on the same
cohort. The fixed material baseline is evaluated on that cohort too.

## Metrics and limitations

Blended MSE compares sigmoid(network cp / 400) to the 90% teacher / 10% game
outcome target. Pure teacher MSE excludes the outcome term. Centipawn MAE,
RMSE and Pearson correlation clip both teacher and prediction to ±2,000 cp.
Decisive sign accuracy uses positions with absolute clipped teacher score at
least 100 cp. Per-phase and tactical/quiet metrics are recorded separately.
These sigmoid values are a chosen regression scale, not calibrated WDL.

Examples processed, epoch counts, aggregate training/validation epoch seconds,
peak PyTorch CUDA allocations, and theoretical dense-head MACs are recorded.
Different dataset sizes process different numbers of examples under the same
epoch cap, so this is a practical scaling study, not a fixed-compute causal
estimate. Source metadata and tactical tags are heuristic. Exact duplicate
prevention cannot remove every near-duplicate or truncated-game alias.

Exports use the existing `SBNNUE1` float32 format with dimensions read from the
header. Independently named candidates, 128 validation golden FENs, checksums,
NumPy/PyTorch/device parity and read-only native parser acceptance are required.
Native inference speed, matches, integration and engine optimization are outside
this task. All v1 weights and checkpoints are protected by hashes.

## Rebuilding from the retained raw archives

Keep the original project/results intact. In a separate project copy with fresh
v2 data, reports, runs and exports directories, retain the raw archives, the
exact teacher binary, the v1 processed split database and the compatible v1 cache.
Then run these stages from the training directory:

```powershell
.\.venv\Scripts\python.exe -m stockbear.v2 inventory
.\.venv\Scripts\python.exe -m stockbear.v2 pool
.\.venv\Scripts\python.exe -m stockbear.v2 benchmark
.\.venv\Scripts\python.exe -m stockbear.v2 run
```

Inventory caching also checks that the selected game records still exist in its
SQLite database and that the sampling seed matches. A missing selection database
is rebuilt by streaming the archives; it cannot silently produce an empty pool.
For normal continuation in the completed original project, only `run` is needed.
