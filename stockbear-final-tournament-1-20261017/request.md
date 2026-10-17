# StockBear — Tournament 1: NNUE Stage 1 vs Hiddenclip

## Mission

Conduct the final head-to-head NNUE inference tournament between the two strongest StockBear implementations:

- **NNUE_STAGE1:** The accepted Stage 1 optimized float32 inference engine.
- **NNUE_HIDDENCLIP:** The Stage 3 vectorized hidden-clipping candidate.

Run exactly **80 games at 500 milliseconds per move**, using 40 opening positions played twice with reversed colors.

The objective is to select the NNUE implementation that will advance to Tournament 2 against StockBear's classical engine.

This is a playing-strength experiment, not an inference benchmark.

Do not modify engine code, model weights, evaluation logic, search algorithms or production configuration.

Do not run Tournament 2 or perform cleanup.

---

## 1. Project context

Project root:

`Z:\Code\Chess`

Read the existing reports and tournament infrastructure, particularly:

- Stage 1 NNUE optimization report.
- Stage 3 dense-head optimization report.
- Stage 3.1 hidden-clipping validation report.
- Previous NNUE-versus-classical tournament reports.
- Existing tournament harness and opening-suite documentation.

Locate these files by their actual paths.

Relevant existing workspaces:

`Z:\Code\Chess\nnue-optimization-stage3-20261017`

`Z:\Code\Chess\nnue-validation-stage3-1-20261017`

Create a new isolated workspace:

`Z:\Code\Chess\stockbear-final-tournament-1-20261017`

Keep all new tournament scripts, logs, PGNs, results and reports inside this workspace.

Do not overwrite earlier experiments.

Do not change the active StockBear engine.

---

## 2. Exact competitors

### Competitor A — NNUE_STAGE1

Use the preserved Stage 1 optimized engine executable.

Expected SHA-256:

`e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d`

Verify that the intended Stage 1 NNUE kernel is selected.

### Competitor B — NNUE_HIDDENCLIP

Use the exact Stage 3 hidden-clipping executable.

Expected SHA-256:

`68ced7162b20109b6ad9e705bbb4f43317c85d2cb5d10ff3ae45a02eb0bd571b`

Verify that the hiddenclip implementation is selected.

Do not rebuild either engine.

Do not substitute other executables.

### Identical neural network

Both competitors must use the same frozen 64/32 NNUE model.

Architecture:

`780 features → dual 64 accumulators → 32 hidden → 1 output`

Checkpoint SHA-256:

`7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`

Export SHA-256:

`a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`

Weights are embedded in the preserved binaries.

Verify both executables' model provenance against their original build manifests.

These two competitors must differ only in their intended inference implementation.

If this cannot be established, stop and report the discrepancy.

---

## 3. Tournament configuration

Run exactly:

**80 games total.**

Use:

- 40 distinct opening positions.
- Two games per opening.
- Reverse colors for the second game.
- 500ms per move, per engine.
- One search thread.
- 16 MiB transposition table.
- No pondering.
- Identical UCI options except the necessary kernel selection.
- Identical CPU-affinity policy.
- Identical opening history and game-state initialization.

Each engine must play:

- 40 games as White.
- 40 games as Black.

Use a balanced execution order.

Do not run additional official games beyond the frozen 80.

---

## 4. Opening suite

Prefer the verified opening infrastructure already used by StockBear.

Create or reuse a balanced suite of 40 opening positions.

Include a mixture of:

- Open games.
- Closed games.
- Semi-open games.
- Queen's-pawn openings.
- Tactical positions.
- Quiet positional positions.
- Different pawn structures.

Use established legal opening sequences.

Validate every position and its complete move history with the existing trusted chess-rules library.

Store:

- Opening ID.
- Opening description.
- Complete move sequence.
- Final FEN.
- Source or construction method.

Freeze the opening suite before the official tournament begins.

Do not select openings based on which NNUE implementation performs better.

Both engines must receive the same opening history, not merely the same final FEN, so repetition and other history-dependent rules are handled correctly.

---

## 5. Time control

**500 milliseconds per move.**

Use:

`go movetime 500`

or the existing verified equivalent.

Confirm that both binaries interpret this time control consistently.

Do not use 1000ms.

Do not replace equal-time play with equal-node play.

### Timing fairness

Record actual wall-clock thinking time and engine-reported search time.

Use the same move-time enforcement policy for both engines.

Define a reasonable, symmetric protocol timeout tolerance before starting.

Distinguish minor scheduling overhead from genuine time-control failures.

Do not allow one engine to receive additional thinking time.

Do not change the time control after observing results.

---

## 6. Hardware and environmental fairness

Run on the existing Windows laptop.

Keep AC power connected.

Do not change:

- Windows power plan.
- NitroSense mode.
- Process priority.
- Security settings.
- Unrelated applications.

Run games serially.

Use identical CPU-affinity and thread policies for both engines.

Reuse the previously verified CPU0 policy if suitable.

If the existing tournament harness uses another validated common affinity policy, document it and apply it symmetrically.

Record available environmental diagnostics:

- AC status.
- Background CPU activity.
- Search wall time.
- Process CPU time, if available.
- Timeouts.
- Abnormal delays.

Do not claim measured CPU frequency or thermal throttling without reliable telemetry.

Balance the order of opening pairs across the tournament to reduce systematic drift.

---

## 7. Preflight verification

Before starting the official 80 games, verify:

1. Both executable hashes.
2. Correct NNUE kernels.
3. Identical embedded model.
4. Identical search settings.
5. UCI initialization and readiness.
6. Correct `go movetime 500` handling.
7. Legal move generation.
8. Complete opening-history reconstruction.
9. Color reversal.
10. Game-state reset.
11. Fresh transposition-table policy.
12. Legal draw and checkmate detection.
13. PGN recording.
14. Checkpoint and resume functionality.
15. No modifications to production files.

Run a small smoke test.

Exclude smoke-test games from official results.

Fix tournament-harness defects if necessary, but do not change engine source or binaries.

If an engine-identity or correctness problem cannot be resolved without changing an engine, stop and report it.

---

## 8. Tournament execution

Use the existing verified StockBear tournament infrastructure where possible.

For each scheduled game:

1. Initialize both engines.
2. Apply the frozen opening sequence.
3. Verify the authoritative board state.
4. Give the side to move exactly 500ms of nominal search time.
5. Validate the returned move.
6. Update the authoritative board state.
7. Record move statistics.
8. Continue until a rules-based result or predeclared adjudication.
9. Save the complete game record and PGN.

Use a trusted chess-rules implementation for checkmate, stalemate, repetition, the fifty-move rule and insufficient material.

Avoid aggressive evaluation-based win adjudication.

Predeclare a maximum-ply safeguard and how games reaching it will be recorded.

Apply the same crash, illegal-move and timeout policies to both competitors.

Preserve the full logs for any abnormal result.

Do not silently replay unfavorable games.

---

## 9. Standalone execution and checkpointing

The tournament may run for a substantial period.

Build or reuse a standalone runner that can execute all 80 games without requiring Codex to issue each move interactively.

Requirements:

- Freeze the complete schedule before starting.
- Save every completed game immediately.
- Persist PGNs and structured results.
- Maintain a progress manifest.
- Resume after interruption.
- Skip already completed games.
- Preserve opening and color assignments.
- Prevent duplicate game IDs.
- Validate saved results before marking games complete.

If the Codex interaction ends, the local runner should continue independently where supported.

If it cannot remain running, it must resume safely when restarted.

Provide simple PowerShell commands to start, check and resume the tournament.

Do not rely on Codex remaining connected for the entire tournament.

---

## 10. Record game and search data

For every game, record:

- Game ID.
- Opening ID.
- White engine.
- Black engine.
- Final result.
- Result reason.
- Number of plies.
- Game duration.
- Complete PGN.
- Engine errors or warnings.

For each move, record where available:

- Engine.
- Side to move.
- Wall search time.
- Engine-reported time.
- Nodes.
- NPS.
- Completed depth.
- Selective depth.
- Score.
- Principal variation.
- Evaluation calls.
- Quiescence nodes.

Preserve detailed logs for reproducibility.

---

## 11. Statistical analysis

After all 80 games, calculate:

- Stage 1 wins.
- Hiddenclip wins.
- Draws.
- Total score.
- Score percentage.
- White/Black performance.
- Average game length.
- Median completed depth.
- Median NPS.
- Median actual search time.
- Time-control compliance.

### Score calculation

For each engine:

`score = wins + 0.5 × draws`

`score_percentage = 100 × score / 80`

### Elo-equivalent estimate

For a score fraction `p` strictly between 0 and 1:

`Elo_difference = -400 × log10(1/p - 1)`

Report the uncertainty.

Do not interpret this as an absolute engine Elo rating.

### Confidence intervals

Because every opening is played with reversed colors, use opening-pair-aware confidence intervals.

Prefer a paired-opening bootstrap or another statistically defensible method.

Report the score estimate and uncertainty.

If the interval includes 50%, do not claim statistically convincing superiority.

Do not infer that a small score lead proves one implementation is stronger.

---

## 12. Winner selection

This tournament must produce a **practical NNUE finalist** for Tournament 2.

But distinguish the practical selection from statistical proof.

### Rule A — Convincing result

If one engine has a statistically convincing score advantage, select that engine.

### Rule B — Inconclusive result

If neither engine demonstrates a convincing advantage, select **NNUE_HIDDENCLIP** as the practical finalist, provided:

- No correctness failures occurred.
- No serious engine instability occurred.
- Time-control behavior is acceptable.
- Its inference throughput advantage remains supported by the previous controlled benchmarks.

The reason is that both implementations use bitwise-identical evaluation outputs, while hiddenclip has repeatedly shown approximately 6–8% higher whole-engine throughput.

This is an engineering tiebreak, not evidence of proven higher Elo.

### Rule C — Equal score

If the tournament finishes exactly tied, apply Rule B.

### Rule D — Serious reliability problem

If either engine suffers a reproducible correctness, legality or stability failure, document it and do not automatically select that engine.

If the result cannot be interpreted reliably, return **NO VALID FINALIST** and explain why.

Do not change these rules after seeing the results.

---

## 13. Interpret the results

Answer:

1. Which NNUE implementation scored higher?
2. What were the win/draw/loss totals?
3. What were the score percentages?
4. Was the difference statistically convincing?
5. Did hiddenclip search more nodes at equal time?
6. Did hiddenclip reach greater completed search depth?
7. Were there any time-control or stability problems?
8. Did the extra inference throughput produce a measurable playing-strength advantage?
9. Which implementation should advance to the classical showdown?
10. How confident should we be in that selection?

Do not claim that higher NPS guarantees higher playing strength.

Do not claim a small tournament proves a precise Elo difference.

---

## 14. Deliverables

Create:

`STOCKBEAR_TOURNAMENT_1_REPORT.md`

Include:

- Executive summary.
- Exact engine identities and hashes.
- Frozen tournament configuration.
- Opening suite.
- Preflight verification.
- Win/draw/loss results.
- Score percentages.
- Opening-pair-aware confidence intervals.
- Elo-equivalent estimate with uncertainty.
- Color-separated results.
- Search-speed comparisons.
- Search-depth comparisons.
- Time-control compliance.
- Crashes, illegal moves and adjudications.
- Finalist selection and rationale.
- Limitations.
- Recommendation for Tournament 2.

Also preserve:

- `games.pgn`
- `games.csv`
- `moves.csv`
- `opening-suite.json`
- `schedule.json`
- `tournament-config.json`
- `progress.json`
- `analysis.json`
- `environment.json`
- `manifest.json`
- Tournament scripts.
- Reproduction instructions.

Use equivalent actual filenames where appropriate.

---

## 15. Finalist handoff

Create a machine-readable handoff file:

`TOURNAMENT_1_FINALIST.json`

Include:

- Selected engine name.
- Selected executable path.
- Executable SHA-256.
- NNUE model identity.
- Required UCI options.
- Search configuration.
- Tournament result.
- Selection rule applied.
- Statistical confidence or uncertainty.
- Any unresolved concerns.

This file will be the input for Tournament 2.

Do not edit the active engine.

Do not copy the finalist over production executables.

Do not delete the losing implementation.

Do not run the classical showdown yet.

---

## 16. Final integrity check

Before finishing:

1. Confirm exactly 80 valid scheduled games.
2. Confirm 40 opening pairs with reversed colors.
3. Confirm each engine played 40 games as White and 40 as Black.
4. Confirm all PGNs are parseable.
5. Confirm recorded results match the games.
6. Confirm no duplicate or missing game IDs.
7. Confirm the original engine executables remain unchanged.
8. Confirm the model files remain unchanged.
9. Confirm no training or labeling occurred.
10. Confirm Tournament 2 has not started.
11. Confirm no cleanup was performed.

If the tournament is incomplete, preserve progress and report the actual completed count instead of inventing a final result.

---

## Final instruction

**Run Tournament 1 only: NNUE_STAGE1 versus NNUE_HIDDENCLIP, exactly 80 games at 500ms per move, using 40 color-reversed opening pairs.**

Execute the tournament using a reproducible standalone runner, preserve all game and search data, perform opening-pair-aware statistical analysis, and select the practical NNUE finalist using the frozen decision rules.

Produce the final report and `TOURNAMENT_1_FINALIST.json`.

**Do not start Tournament 2, modify the active engine, retrain NNUE, or clean up any project files.**