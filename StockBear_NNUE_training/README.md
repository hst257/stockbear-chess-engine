# StockBear NNUE training

Standalone PyTorch training for a custom efficiently updatable chess evaluator.
Streams the existing June–September 2026 Lichess broadcast PGNs and uses the
downloaded Stockfish 19 teacher. No classical C++ engine integration is included.

The project contains deterministic whole-game splits, exact position
deduplication, resumable teacher caches, sparse feature sums, clipped ReLU,
reproducible CUDA/CPU training, early stopping, full recovery checkpoints,
diagnostics, tests and a documented portable float32 export.

## Install and run

Use Python 3.11. From this directory in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m stockbear run --config configs/pilot.json
.\.venv\Scripts\python.exe -m stockbear diagnostics --config configs/pilot.json
# Review the pilot, then execute the bounded larger run:
.\.venv\Scripts\python.exe -m stockbear run --config configs/full.json
.\.venv\Scripts\python.exe -m stockbear diagnostics --config configs/full.json
```

For CPU-only installation, substitute `requirements-cpu.txt`. GPU training uses
the pinned CUDA 12.8 PyTorch wheel and automatically checks CUDA availability.
The existing environment is already prepared by the execution accompanying this
project; do not recreate it merely to inspect the results.

`run --resume` resumes a matching existing training run. Sampling and labeling
always reuse completed matching work. Each phase can also be invoked separately:
`audit`, `sample`, `label`, `validate`, `train`, `export`, `diagnostics`.

## Files

| Path | Purpose |
|---|---|
| `data/raw/*.pgn.zst` | Existing compressed input archives, never expanded in full |
| `stockfish*/` | Existing teacher distribution, kept in place |
| `configs/pilot.json` | 64 selected games per month, up to 2048 positions |
| `configs/full.json` | 2000 selected games per month, up to 64000 positions |
| `configs/compact.json` | Selected smaller model, using the same full dataset |
| `data/processed/*.sqlite` | Deduplicated positions with game-grouped partitions |
| `data/cache/teacher.sqlite` | Teacher-profile keyed labels and retained failures |
| `runs/pilot`, `runs/full` | Audits, metrics, history, diagnostics, checkpoints |
| `exports/*.sbnnue` | Custom portable float32 networks and golden FEN scores |
| `reports/` | Compact versioned record of the actual execution |
| `docs/PHASES.md` | Detailed sampling, recovery, validation and reproducibility |
| `docs/EXPORT_SPEC.md` | Feature indices, accumulator math and binary layout |

## Model and interpretation

Two 780-feature perspectives share a feature transform. Evaluation
concatenates side-to-move/opponent accumulators, applies clipped ReLU, then a
hidden layer and scalar output. The initial 128/32 model has 108353 parameters;
the selected 32/16 compact model has 26081 parameters. Only active
feature rows are summed; a future engine can update each accumulator by adding
and subtracting changed rows, including special moves and legal state features.

Weights and accumulators remain float32. This is an NNUE-style architecture
with its own `.sbnnue` contract; it is not Stockfish's current architecture or
its `.nnue` binary format. Integer quantization and engine integration are future
work. The exported centipawn score is always from the side-to-move perspective.

The training target mixes 90% transformed teacher score with 10% game outcome.
Validation selects checkpoints; the test split does not select epochs. Reports
compare against constant and simple material baselines, include game-bootstrap
confidence intervals, and expose worst FEN errors. A completed training run is
not evidence of Elo or an improvement over the classical engine. Check the
actual metrics and baseline comparison before using a network.

See the execution report in `reports/RESULTS.md` for measured results and limits.
The compact candidate was selected by validation loss before its test scores
were computed. Its smaller capacity and stronger weight decay reduced the
generalization gap. The selected export is `exports/stockbear-compact.sbnnue`.
