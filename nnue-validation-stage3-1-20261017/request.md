# StockBear — Stage 3.1: Independent Validation of Vectorized Hidden Clipping

## Mission

Perform a rigorous, independent validation of the existing Stage 3 `hiddenclip` optimization.

The candidate has already demonstrated:

- **1.0642×** whole-engine throughput at 1,000,000 fixed nodes.
- **1.0768×** throughput at 1,000ms.
- **1.1146×** inference-head throughput with 128 rotating frames.
- Bitwise-identical inference outputs.
- Exact fixed-work search parity.

However, Stage 3 classified the candidate as **INCONCLUSIVE** because the piece-endgame fixture at 100ms showed a median factor of 0.9300×, corresponding to 7.53% more elapsed time.

The seven original measurements were inconsistent, and the repeat-only uncertainty interval crossed 1.0.

**Your job is to determine whether the hidden-clipping optimization is reliably faster and whether the endgame regression is reproducible.**

This is a validation-only study.

Do not change the implementation, compile a modified candidate, tune the algorithm, or create new optimization variants.

Do not automatically promote the candidate into production.

---

## 1. Project context

Project root:

`Z:\Code\Chess`

Read:

- `NNUE_PROFILING_REPORT.md`
- `NNUE_OPTIMIZATION_ROADMAP.md`
- `NNUE_STAGE1_OPTIMIZATION_REPORT.md`
- `NNUE_STAGE2_OPTIMIZATION_REPORT.md`
- `NNUE_STAGE2_1_OPTIMIZATION_REPORT.md`
- `NNUE_STAGE3_OPTIMIZATION_REPORT.md`

Relevant experimental branches:

- `codex/nnue-stage1-float-head`
- `codex/nnue-stage3-dense-head`

Existing Stage 3 workspace:

`Z:\Code\Chess\nnue-optimization-stage3-20261017`

Create a separate validation workspace:

`Z:\Code\Chess\nnue-validation-stage3-1-20261017`

Use a dedicated branch if needed for validation scripts and reporting:

`codex/nnue-stage3-1-validation`

Keep the active engine and classical default unchanged.

## 2. Exact binaries and model

Use the existing Stage 1 baseline binary and Stage 3 `hiddenclip` candidate binary.

Locate both from the preserved Stage 3 artifacts and verify their identities using the original Stage 3 manifest.

Do not silently substitute rebuilt executables.

If an original executable or its matching dependencies are missing, stop and report the issue rather than claiming an exact-binary validation.

Verify:

- Executable SHA-256.
- Matching PDB, where relevant.
- Model export SHA-256.
- Selected checkpoint SHA-256.
- Compiler/build provenance.
- NNUE kernel configuration.

Stage 1 baseline executable SHA-256:

`e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d`

Model checkpoint SHA-256:

`7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`

Model export SHA-256:

`a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`

Obtain the exact hiddenclip binary hash from the Stage 3 manifest; do not invent it.

Use:

- One search thread.
- 16 MiB hash.
- `NNUEKernel=clip` as appropriate for the preserved binaries.
- Compact accumulator strategy 2.
- Identical FENs and histories.
- Fresh transposition table per search.
- No pondering.
- Identical UCI settings.

## 3. Preserve the original evidence

The Stage 3 report recorded:

| Control | Hiddenclip / Stage 1 |
|---|---:|
| 200,000 nodes | 1.0530× |
| 1,000,000 nodes | 1.0642× |
| 100ms | 1.0566× |
| 500ms | 1.0632× |
| 1,000ms | 1.0768× |

All five grouped confidence intervals were positive.

The problematic fixture was:

**piece_endgame, 100ms: 0.9300×.**

Its seven individual factors were:

- 0.9285×
- 0.9132×
- 1.0613×
- 1.0490×
- 1.1960×
- 0.9300×
- 0.9050×

The repeat-only interval was approximately:

`[0.9132, 1.0613]`

Do not pool the original Stage 3 results with the new study's primary estimates.

Keep them as historical evidence for comparison.

The new experiment must stand independently.

---

## 4. Phase A — Freeze the validation plan

Before running performance measurements:

1. Define the exact position set.
2. Define the exact search controls.
3. Define the number of repetitions.
4. Define the execution-order schedule.
5. Define the primary statistic.
6. Define confidence-interval methodology.
7. Define the acceptance and rejection thresholds.
8. Define how environmental interruptions are handled.
9. Record a reproducible random seed.

Save this plan to:

`validation-plan.json`

Do not change the plan after seeing candidate performance results.

Do not exclude inconvenient measurements.

Only discard runs for objective, predeclared failures such as a crashed engine, invalid protocol response or externally verified interrupted execution.

Preserve discarded records and reasons.

## 5. Phase B — Controlled environment

The earlier studies ran on a Windows laptop with:

- Intel Core i5-13420H.
- 4 performance cores and 4 efficiency cores.
- Quiet/Eco power profile.
- CPU0 affinity.
- AC power.

The exact NitroSense mode and thermal state were not independently verified.

For this validation, improve environmental monitoring without changing user preferences.

### Requirements

- Confirm AC power before and after each benchmark block.
- Use the same CPU affinity for both binaries.
- Use the same thread count.
- Use the same power plan.
- Avoid concurrent CPU-intensive benchmark processes.
- Run candidates in rotated, balanced order.
- Record background CPU usage.
- Record benchmark process CPU time where available.
- Record effective CPU frequency or per-core frequency telemetry where available.
- Record temperature and throttling information only if reliably accessible.

Do not install kernel drivers or change system-wide security settings.

Do not automatically change NitroSense, Windows power mode, CPU priority or unrelated applications.

If reliable frequency or temperature telemetry is unavailable, say so.

Do not substitute nominal clock speed for measured frequency.

### CPU-time measurement

Where possible, collect process CPU time alongside wall time.

Keep wall time and wall NPS as the primary performance metrics because chess-search time limits are wall-clock based.

CPU-time measurements are diagnostic only.

If CPU-time and wall-time results disagree, investigate the discrepancy without silently replacing the primary metric.

### Background-load policy

Predeclare a reasonable background-load threshold for pausing or flagging a benchmark block.

Apply it symmetrically to baseline and candidate.

Do not filter individual results based on which engine was faster.

Record every pause, interruption and resumed block.

If environmental variation remains excessive, return **INCONCLUSIVE** rather than manufacturing a positive result.

---

## 6. Phase C — Independent endgame validation set

Retain the original frozen 12-position suite unchanged.

Create an additional endgame validation set containing approximately 12–20 legal positions, including:

- Quiet pawn endgames.
- Piece endgames.
- Rook endgames.
- Minor-piece endgames.
- Material imbalances.
- Positions with few legal moves.
- Positions with many legal moves.
- Endgames involving checks and tactical captures.

Include the original problematic `piece_endgame` fixture as a separately identified sentinel position.

Use independently selected positions, not variations chosen because they favor the candidate.

Ensure each position has a legal, reproducible FEN and any required history.

Freeze this set before benchmarking.

The original frozen suite remains the primary general-performance sample.

The new endgame suite is a separate regression-validation sample.

Do not pool the two sets into a single headline speedup.

Do not treat many positions from one game as independent if they are highly correlated.

---

## 7. Phase D — Focused 100ms regression test

The primary diagnostic target is the original piece-endgame anomaly.

Benchmark:

- Stage 1 baseline.
- Stage 3 hiddenclip.

Use identical UCI options and search setup.

Controls:

- 100ms.
- 200ms.
- 500ms.
- 1,000ms.
- 200,000 fixed nodes.
- 1,000,000 fixed nodes.

The 100ms test is especially important because that was the original failure.

### Repetitions

Use a predeclared schedule of approximately 12 balanced paired repetitions per position/control for the focused endgame study, subject to a fixed runtime budget.

Alternate order:

- Baseline → candidate.
- Candidate → baseline.

Use balanced randomized blocks with a recorded seed.

If the planned workload is too large, reduce the number of endgame positions or secondary controls before collecting results, and document the frozen reduced plan.

Do not change the schedule based on observed gains or losses.

### Record for every search

- Position identifier.
- Engine binary hash.
- Execution order.
- Wall elapsed time.
- Engine-reported search time.
- Process CPU time.
- Wall NPS.
- Actual nodes.
- Completed depth.
- Selective depth.
- Best move.
- Score.
- Principal variation.
- Evaluation calls.
- Quiescence nodes.
- Search counters.
- Background CPU load.
- Frequency/thermal telemetry, if available.

For fixed-node searches, verify that the two binaries perform identical work and produce identical search decisions.

For timed searches, do not require identical moves or completed depths.

### Important distinction

At 100ms, small changes in timing may affect how much of the next iterative-deepening iteration completes.

Do not confuse an unfinished iteration with a correctness defect.

Investigate whether the observed regression comes from:

- Lower sustained search throughput.
- Variation in node completion.
- Search-depth boundary effects.
- OS scheduling.
- Background CPU contention.
- CPU-frequency variation.
- Measurement noise.

Only claim a cause supported by actual evidence.

---

## 8. Phase E — Fresh general-performance validation

Repeat the original frozen 12-position suite independently.

Controls:

- 200,000 nodes.
- 1,000,000 nodes.
- 100ms.
- 500ms.
- 1,000ms.

Use ten predeclared paired repetitions per position/control.

Balance execution order and rotate positions.

Do not pool these new observations with the original Stage 3 experiment for the primary conclusion.

Calculate:

- Per-position median paired speedup.
- Position-grouped geometric mean speedup.
- Grouped 95% uncertainty intervals.
- Order-specific estimates.
- Fixed-node inverse wall-time ratios.
- Timed-search wall-NPS ratios.
- Worst observed position/control medians.

Use a hierarchical bootstrap or another defensible method that treats positions as independent groups and paired repetitions as nested measurements.

Also inspect temporal drift and repeated-measure dependence.

Do not claim that the resulting intervals eliminate systematic thermal or scheduling bias.

---

## 9. Phase F — Correctness and binary integrity

Since the source code and binaries are unchanged, do not repeat unnecessarily expensive development tests unless required to verify the environment.

However, confirm:

- Both binaries match their recorded hashes.
- Both load the identical NNUE export.
- Both produce identical fixed-work results.
- Both preserve search interruption behavior.
- No UCI defaults have changed.
- Classical remains the default in the active engine.
- No protected source/model files changed.

Use the existing Stage 3 correctness receipts as historical evidence.

Run a fresh representative fixed-work parity suite on the validation positions.

If any fixed-work result differs, investigate and classify it as a correctness failure rather than continuing to acceptance.

Do not silently rebuild a binary to repair parity.

---

## 10. Statistical analysis

The primary performance metric is the paired wall-NPS ratio, summarized as the geometric mean of per-position median log ratios.

For fixed-node tests, also report the equivalent inverse wall-time factor.

Calculate separate results for:

1. Frozen general-position suite.
2. Independent endgame validation suite.
3. Original piece-endgame sentinel.
4. Each search control.

Report:

- Point estimates.
- Grouped 95% intervals.
- Per-position medians.
- Order sensitivity.
- Run-to-run variation.
- Environmental sensitivity.
- Material regressions.

For the original sentinel position, report an uncertainty interval based on its paired repetitions, explicitly distinguishing it from a position-grouped interval.

Do not call a sentinel repeat-only interval an across-position confidence interval.

Do not translate throughput improvement into Elo.

Do not calculate an Elo estimate without chess games.

---

## 11. Predeclared decision criteria

Use the following conservative decision framework.

### ACCEPTED

Accept hiddenclip as the **new experimental NNUE baseline** only if all conditions hold:

1. Exact binary and model identities are verified.
2. Fixed-work correctness passes.
3. The frozen general-position suite shows a positive grouped throughput gain at both 1,000,000 nodes and 1,000ms.
4. The frozen suite's other controls show no convincing aggregate regression.
5. The independent endgame suite shows no convincing systematic regression at 100ms.
6. The original piece-endgame sentinel does not show a reproducible material regression.
7. There are no unexplained material position/control regressions that undermine the result.
8. Execution-order and environmental diagnostics do not contradict the claimed gain.

A material regression is more than 3% additional elapsed time in a position/control median.

Distinguish an observed median exceeding that threshold from a statistically established regression.

Do not require every noisy individual measurement to be positive.

If a material median appears, investigate its repeat uncertainty and consistency across controls/positions before deciding whether it is an established defect.

Do not relax these criteria after examining the results.

### REJECTED

Reject hiddenclip if:

- Correctness fails.
- A reproducible material regression is established.
- The candidate consistently underperforms Stage 1.
- The supposed aggregate gain disappears under controlled validation.

### INCONCLUSIVE

Return INCONCLUSIVE if:

- Environmental noise remains excessive.
- Performance intervals are too wide.
- Endgame results conflict materially.
- A concerning regression remains unresolved.
- Evidence cannot distinguish a genuine gain from measurement variation.

Do not use a simple majority of winning runs as the sole acceptance criterion.

---

## 12. Time and resource limits

This is a bounded validation study.

Aim for a reasonable total benchmark runtime, preferably under approximately 60–90 minutes if practical.

Estimate runtime before beginning.

Avoid unlimited repetitions.

Do not run chess tournaments.

Do not train networks.

Do not label data.

Do not use the sealed test split.

Do not begin Stage 4.

Do not implement any new optimization.

If the plan cannot be completed within a reasonable budget, report the limitation rather than silently weakening the analysis.

---

## 13. Deliverables

Create:

`NNUE_STAGE3_1_VALIDATION_REPORT.md`

Include:

1. Executive decision: ACCEPTED / REJECTED / INCONCLUSIVE.
2. Exact baseline and candidate binary identities.
3. Frozen benchmark plan.
4. Environmental controls and available telemetry.
5. Original endgame anomaly.
6. Fresh sentinel results.
7. Independent endgame suite results.
8. Fresh frozen-suite results.
9. Fixed-work correctness.
10. Per-position gains and regressions.
11. Uncertainty intervals.
12. Execution-order effects.
13. CPU-time/frequency findings.
14. Remaining limitations.
15. Recommendation for the next stage.

Preserve:

- `validation-plan.json`
- Raw CSV/JSON search results.
- Position manifests.
- CPU/environment telemetry.
- Binary hashes.
- Correctness receipts.
- Analysis scripts.
- Reproduction instructions.
- Final integrity manifest.

Keep all artifacts in:

`Z:\Code\Chess\nnue-validation-stage3-1-20261017`

Do not overwrite the previous Stage 3 report or measurements.

---

## 14. Final questions

Answer explicitly:

1. Was the original 100ms piece-endgame slowdown reproducible?
2. What was the fresh sentinel median and uncertainty interval?
3. Did the independent endgame suite show any systematic slowdown?
4. Did the frozen 12-position suite reproduce the 6–8% gain?
5. What were the fixed-node and timed-search speedups?
6. Were the results sensitive to execution order?
7. Did CPU-time or frequency evidence explain any anomalies?
8. Were fixed-work results identical?
9. Did any material regressions remain?
10. Should hiddenclip replace Stage 1 as the accepted **experimental** NNUE baseline?
11. What is the next highest-value optimization opportunity?

**Proceed with the independent Stage 3.1 validation. Preserve the exact Stage 1 and hiddenclip binaries, make no implementation changes, and do not promote anything into the active engine without my approval.**