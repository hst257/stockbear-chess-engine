# Execution and reproducibility

Run commands from `StockBear_NNUE_training` with its `.venv/Scripts/python.exe`.

## 1. Audit

`python -m stockbear audit --config configs/pilot.json`

Records source hashes, teacher hash/UCI identity, Python/package versions, CPU,
RAM, free disk, GPU/runtime and a real CUDA matrix operation. The downloaded
teacher may live in either `stockfish/` or its existing `stockfish-*/stockfish/`
directory. Exactly one matching executable is required; nothing is relocated.

## 2. Sample

`python -m stockbear sample --config configs/pilot.json`

Two streaming passes per zstd archive: a bounded priority reservoir over game
headers selects games across the *entire* month, then only those games' mainlines
are parsed. No whole-file decompression or all-position RAM list is used.
Comments/variations are skipped. For each selected completed standard game,
reservoir-sample up to eight quiet, nonterminal positions from plies 16–180,
separated by at least four eligible plies. A candidate follows a noncapture,
nonpromotion move and is not in check; this is a quiet-position heuristic, not a
quiescence proof. Invalid/incomplete games are omitted and counted.

Game identity hashes normalized event/date/round/white/black headers, excluding
live-changing results/ply count. A separately seeded hash assigns the entire
game to 80/10/10 train/validation/test. Duplicate canonical positions are unique
globally in SQLite and assigned to their first encountered game, preventing
exact FEN overlap across partitions. Snapshot header aliases can evade game
identity; the report therefore makes no claim of detecting every near-duplicate
or transposed game. Missing headers conservatively group games together.

Source checksums and configuration are locked into the dataset. Resampling the
same configuration is idempotent; changed source/configuration requires a new
dataset path. Work already committed in a partially processed month is safe to
replay. Completed-month cursors avoid reprocessing finished months.

## 3. Label and recover

```
python -m stockbear label --config configs/pilot.json --limit 64
python -m stockbear label --config configs/pilot.json
python -m stockbear validate --config configs/pilot.json
```

The first command intentionally stops after 64 new labels; the second resumes.
SQLite commits at most 128 labels per batch. A hard process interruption can
repeat that final batch, never corrupt completed labels. Each position gets up
to three attempts with teacher restart on a process error/timeout. Failed rows
are retained with an error and must be inspected before training. A changed
teacher binary, node budget, or profile produces distinct cached labels.
Four single-thread workers with 64 MiB hash each bound teacher CPU/RAM usage.

## 4. Pilot, then full run

```
python -m stockbear train --config configs/pilot.json --stop-after 2
python -m stockbear train --config configs/pilot.json --resume
python -m stockbear export --config configs/pilot.json
python -m stockbear run --config configs/full.json
```

Pilot samples 64 games/month, up to 2048 positions total. Full v1 samples 2000
games/month, up to 64000 positions total. Both use 16384-node teacher searches so
the larger run can reuse overlapping pilot labels. The pilot must pass tests,
show finite improving losses, resume successfully and pass export parity before
the full command is executed. This is an initial bounded full run over all four
months; it does not consume every game or constitute production-strength data.

Training reads compact memory-mapped feature arrays in shuffled batches. Sparse
row lookup/sum avoids dense board inputs. AdamW's gradients are dense for this
small table, enabling consistent weight decay. CUDA is automatic when available;
fused AdamW and pinned batch transfers are used on GPU. Accumulators and weights
remain float32; AMP/TF32/compilation are not enabled blindly for this small
network. They require measured parity/throughput benefit before future use.

Reproducibility controls: fixed Python/NumPy/torch seeds, deterministic torch
algorithms, CUBLAS workspace config, TF32 off, stable source/teacher/dataset
fingerprints and epoch-seeded shuffle. Exact reproducibility is scoped to the
same software, hardware, device and thread settings. Node-limited teacher
searches are more reproducible than time-limited searches; external binaries
still have their own implementation behavior.

Overfitting controls: game holdouts, position deduplication, bounded per-game
samples, modest architectures (108353 initial / 26081 compact parameters), weight decay, gradient clipping,
validation-based LR reduction, minimum-delta early stopping and best-checkpoint
selection. No test scores control model selection. The held-out test is reported
once per completed training invocation; do not tune against it across future
experiments. Historical pilot/full test memberships overlap by design because
the game split seed is fixed; treat pilot test metrics as engineering checks,
not an untouched final publication holdout.

`last.pt` includes model, optimizer, LR scheduler, RNG states, epoch, history and
signatures. `best.pt` selects the lowest validation loss. Resume rejects changed
features/data/training settings; increasing the epoch ceiling is allowed.
Checkpoints are local trusted PyTorch files; use the portable export for serving.

## 5. Validate and export

The completed execution also includes `configs/compact.json`, using the same
dataset with width=32, hidden=16, weight decay=0.05 and learning rate=0.0015.
The initial 128/32 model's validation gap motivated this capacity comparison.
Use `train --validation-only` to report training/validation scores while
selecting a candidate. Save the validation-based choice before a final
`train --resume` computes the selected candidate's test diagnostics.
`reports/selection.json` records the actual comparison. Compact training reused
the full dataset/teacher evidence; those audits remain in `reports/full`.

```
python -m pytest
python -m stockbear export --config configs/full.json
```

Reports include probability MSE, clipped centipawn MAE/RMSE, balanced-position
MAE, decisive-position sign accuracy, score percentiles, phase/month metrics,
constant/material baselines, worst-error FENs, learning history, CUDA memory and
NumPy/PyTorch export parity. No Elo or playing-strength claim follows from
supervised evaluation error; that needs future engine integration and matches.

If validation stalls or worsens, early stopping retains the best model. If the
network fails to beat the material baseline, record that limitation and improve
data/teacher/model in a new version rather than promoting the artifact silently.
All raw archives, teacher distribution, environments, caches, checkpoints and
binary exports are ignored by Git; code, configs, compact reports and specs are
versioned. Stockfish's existing GPL distribution files are left intact.

## Primary references

- [Stockfish NNUE architecture](https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html)
- [PyTorch EmbeddingBag](https://docs.pytorch.org/docs/stable/generated/torch.nn.EmbeddingBag.html)
- [PyTorch reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html)
- [python-chess UCI interface](https://python-chess.readthedocs.io/en/latest/engine.html)
