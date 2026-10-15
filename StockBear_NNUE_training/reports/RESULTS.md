# StockBear NNUE — measured execution report

Executed on 15 October 2026 in `Z:\Code\Chess\StockBear_NNUE_training`. The project builds, trains, validates and
exports a standalone custom evaluator. The classical C++ engine was not changed.

## Result

The selected compact run completed on **NVIDIA GeForce RTX 4050 Laptop GPU**, using **56,721
unique positions from 7,459 games**. Its held-out teacher
probability MSE is **0.016341**, 17.6% lower than
the simple material baseline. The exported network is **105,484
bytes**. This establishes a reproducible initial training result, not playing
strength or an Elo estimate.

| Measurement | Pilot | Selected full model |
|---|---:|---:|
| Training positions | 1,505 | 45,450 |
| Validation positions | 191 | 5,653 |
| Test positions | 193 | 5,618 |
| Test games | 26 | 735 |
| Device | cpu | cuda |
| Epochs completed / selected | 10 / 2 | 20 / 10 |
| Validation teacher probability MSE | 0.030177 | 0.016718 |
| Test teacher probability MSE | 0.028473 | 0.016341 |
| Constant baseline test MSE | 0.030201 | 0.035670 |
| Material baseline test MSE | 0.014868 | 0.019836 |
| Test clipped cp MAE | 223.13 | 197.79 |
| Test clipped cp RMSE | 363.99 | 309.96 |
| Test balanced-position cp MAE | 108.12 | 142.61 |
| Test decisive-position sign accuracy | 70.5% | 86.6% |

The full test MSE's 95% game-bootstrap interval (500 resamples) is
[0.015284,
0.017502]. This interval accounts for
within-game dependence; it is not an estimate of the teacher's own error.
All cp MAE/RMSE values clip both teacher and predictions to ±2000 cp.
Balanced means absolute teacher score ≤500 cp. Sign accuracy uses |teacher|≥100 cp.

## Capacity selection

The first 108353-parameter full model selected epoch 8
and scored 0.020371 validation
blended MSE, with a 0.016252 train/validation gap.
Its test teacher MSE was 0.018443.
The observed validation gap motivated one smaller model, with 26081 parameters,
weight decay 0.05 and learning rate 0.0015. It selected epoch 10
and achieved 0.018856 validation blended
MSE, reducing the gap to 0.010686.

The compact model's test metrics were not computed until `selection.json` saved
the decision based on validation blended MSE. There were no further experiment
choices based on test scores. The final candidate still has a material
generalization gap and should be treated as an initial experimental evaluator.

## Hardware and environment

- CPU: 13th Gen Intel(R) Core(TM) i5-13420H; 8 physical / 12 logical cores.
- RAM: 31.71 GiB.
- GPU: NVIDIA GeForce RTX 4050 Laptop GPU; 6.00 GiB VRAM.
- Runtime: Python 3.11.8; PyTorch 2.7.1+cu128; bundled CUDA 12.8.
- Teacher: Stockfish 19, SHA256 `45bc8e4969147db9c2eb533810637994619bff0eacc81ccfd9854394901bcbd0`.
- Source archives: June–September 2026, 96,757,519 compressed bytes,
  154,612 PGN game records examined per sampling pass.

The standard 3.27 GB CUDA wheel transfer stalled. Downloads were recovered with
HTTP byte ranges and verified against the official server's SHA256. A temporary
CPU PyTorch runtime ran the engineering pilot; the final isolated environment
uses CUDA. This explains the pilot/full device difference. The complete final
package lock is `requirements-lock.txt`.

## Sampling and labeling

Two streaming passes over each compressed archive select a priority reservoir of
2000 game identities per month, then sample up to eight quiet positions per
completed standard game. The sample is spread throughout each month rather than
restricted to the start of a file. The sampler excludes checks, terminal states,
captures/promotions on the preceding move, early openings and very late positions.
This quiet-position filter does not guarantee tactical stability.

Normalized event/date/round/player headers define a game group. Hashes assign
whole groups to 80/10/10 splits. Globally unique canonical FENs prevent exact
position leakage; counters are normalized to 0/1. Validation checked all
56,721 positions: 0 game overlaps,
0 exact FEN overlaps and 0 missing labels.
Header aliases and different transpositions are not fully detected, so the
holdout does not promise elimination of all near-duplicate chess content.

Teacher labeling uses four single-thread workers, 64 MiB hash per worker and
16384 nodes per position at full strength. Clear Hash/new-game state resets
precede every search. Cache keys include binary hash, node budget and label
conversion version. Scores are side-to-move cp; mate distance is stored
separately and converted to ±2000 cp for training.

The full run generated 54,832 new labels, reused the matching
pilot cache and finished with 0 missing labels and
0 new failures. Mean throughput was
72.97 new positions/s over 751.5 seconds.
Search depth min/mean/max: 5 /
14.75 / 245.
Mate-labeled positions: 1,158. A fixed node budget does not
provide a uniform depth or perfect ground truth.

## Training and overfitting

The network uses two sparse 780-feature perspectives, a shared 32-wide summed
feature transform, clipped ReLU, a 16-unit clipped hidden layer and one scalar
output: 26,081 parameters. Its unclipped accumulators support
incremental add/subtract updates. Features include pieces, castling rights and
legal EP file; repetition and exact fifty-move history are outside its static
evaluation contract.

The target is 0.9×sigmoid(clipped teacher cp/400) + 0.1×game outcome.
This chosen transformation is not a calibrated Stockfish win probability.
Training uses shuffled memory-mapped batches, float32 accumulators, fused AdamW
on CUDA, weight decay, gradient clipping, validation-based LR reduction and
early stopping. TF32/AMP/compilation were not enabled without a parity and
throughput justification for this small network.

The pilot deliberately stopped at epoch 2 and resumed. It exposed rapid
overfitting on a tiny sample; early stopping selected epoch 2
and the pilot remained worse than material. The first full CUDA run also stopped
at epoch 2 and resumed, demonstrating recovery on GPU. The selected compact run
completed 20 epochs and selected epoch 10.
Early stopping triggered: True.
Validation–training blended MSE gap at the selected checkpoint:
0.010686. Total measured full training epoch time:
9.58 seconds; final invocation including
feature preparation and evaluation: 11.89 seconds.
Peak CUDA tensor allocation during compact training: 66.61 MiB
(allocator measurement, not total process VRAM).

The test partition did not select epochs or change hyperparameters. Pilot and
full tests share game-based split rules and some content; treat this as an
engineering holdout, not an untouched publication benchmark across experiments.
Per-month/per-phase metrics and worst-error FENs are included in the JSON reports.

## Verification and export

- Final automated suite: **19 passed**, 0 failed, 0 skipped.
- Tests cover feature orientation/padding, sparse forward/backward behavior,
  castling, EP, promotion, capture, king moves, make/unmake sequences, multi-frame
  zstd streaming, deterministic game selection, cache resume/profile isolation,
  mate POV and retries, exact checkpoint recovery, CUDA training/CPU agreement,
  and corrupted-export rejection.
- Real pilot and full teacher repeat checks: 16
  positions each; exact cp/mate/depth/nodes agreement.
- Checkpoint test: interrupted versus uninterrupted training gave bitwise equal
  CPU weights and best loss. Real phase-boundary recovery also completed on CUDA.
- Export comparison: 128 held-out positions,
  max NumPy/PyTorch error **0.00009537 cp**;
  max CPU/training-device error **0.00011444 cp**.
- Payload SHA256: `76de34fb91ee3e835e7dadec926080cbbf37b1df1b14209170a5cb5454e0389d`.

`stockbear-compact.sbnnue` is a custom little-endian float32 format, **not a Stockfish
`.nnue` file**. `EXPORT_SPEC.md` defines exact indexing, tensor layout, scale,
accumulator rules and integrity checks. Golden held-out FEN scores accompany the
export. Integer quantization, classical-engine integration and playing-strength
matches remain future work and were not performed.

## Delivered files

- `stockbear-compact.sbnnue`, adjacent golden scores, and `EXPORT_SPEC.md`.
- `StockBear_diagnostics.png` and the corresponding SVG learning/error plots.
- `StockBear_NNUE_project.zip`: source, pinned configs/dependencies, specs,
  compact reports, portable exports and the selected model's best/last checkpoints.
- The original project retains raw data, teacher distribution, caches,
  prepared features, checkpoints and reports. Generated data/binaries are ignored
  by Git; the training source and compact execution evidence are versioned.

To continue a matching interrupted run, use
`.\.venv\Scripts\python.exe -m stockbear run --config configs/compact.json --resume`.
For a larger or changed experiment, choose new dataset/run/export paths in a
new configuration; do not overwrite the recorded experiment.
