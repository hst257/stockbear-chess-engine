# Resume the final showdown

The user requested a pause after **15 completed games**, then a **single**
continuation in this existing chat at **2026-10-17 03:30 IST** (2026-10-16 22:00 UTC).
Do not continue engine games before that time after reaching 15.

Automation: `resume-final-stockbear-showdown-once`, heartbeat attached to
thread `01a139cf-5c1d-7840-a9e5-05fbd19e7839`, one occurrence only.
The scheduler configuration is stored by the app; do not create a recurring task.

## State and next actions

- Read `scoreboard.json`, `pause-history.json`, `plan.json`, and Git status.
- At the intended pause, G001–G015 are complete; **33 games remain**:
  G016–G024 complete classical vs 64/32, then G025–G048 classical vs 128/32.
- All games use 1000 ms/move, 16 MiB hash, one search thread, no pondering,
  the same fresh 12 opening pairs and the frozen search/engine configurations.
- The actual user request is the attachment
  `C:\Users\sksth\.codex\attachments\c032aff6-cd10-4219-9967-ee8237a6b7be\Pasted text.txt`.
- A temporary Python wake helper under `artifacts/` prevents idle sleep only
  until 03:35 IST, bridging the scheduler handoff. It runs no chess searches.

From `Z:\Code\Chess`, start the remaining games with native subprocess access:

```powershell
.\.venv\Scripts\python.exe -u -m tools.final_nnue_showdown run --resume
```

Use `require_escalated` for native execution in the Codex tool if sandboxed
subprocess startup stalls. No user permission question is needed for this
authorized run. Redirect output to a new log under `artifacts/` and retain
previous `tournament.log` and `tournament-to-15.log`. Completed games are skipped;
partial games preserve legal history and saved searches. The runner is bounded
to G048 and never adds games. Do not call any old showdown runner.

## Verification and preservation

The frozen runner is `tools/final_nnue_showdown.py`, reusing the original
`tools/nnue_showdown.py` game loop via evaluator/PGN adapters. **Do not edit these
or their frozen dependencies:** their hashes are checked on every game/resume.
NNUE 64 and 128 are copied from the previous verified showdown. Classical is
a byte-identical copy of 64 with `Evaluator=classical`; embedded weights are
unused. Startup probes and every move's counters enforce genuine classical
or NNUE evaluation, respectively.

Preflight passed: original classical CLI/UCI probes matched exactly, classical
NNUE search calls were zero, all copies passed clocks/terminal/special-move
checks, 29 fresh targeted regressions and 12 preflight harness checks passed.
The reused distinct NNUE binaries retain prior 38-test regression receipts.
Two additional analysis tests passed. An audit after 12 games replayed their
PGNs/moves/deadlines and found all **491 protected files** unchanged.

G014 was interrupted after 22 searched moves to impose the user's 15-game cap,
then resumed with fresh processes. Record that cold-cache restart as a minor
fairness limitation in the final report; see `pause-history.json`. No completed
game was replayed and no failure was scored as a loss.

## Finish the investigation

1. Complete the remaining frozen schedule, serially. No training, labeling,
   new heuristics, sealed-test access, active engine replacement or extra games.
2. Run `python -m tools.report_final_nnue_showdown` with the root `.venv` Python.
   The analyzer checks 48 unique games, legal full histories, PGN identities,
   evaluator counters, deadlines, and protected-file hashes.
3. Inspect the resulting `analysis.json` and `FINAL_NNUE_SHOWDOWN_REPORT.md`.
   **Finish the evidence-based recommendation section** in
   `tools/report_final_nnue_showdown.py` and regenerate the report. Its current
   generator already covers metrics, uncertainty, identities, example games and
   preservation, but still needs explicit final answers/default recommendation.
4. Explain which models beat classical, whether lower teacher MSE corresponds
   to better games, measured search-speed costs, and the smallest useful next
   experiment if inconclusive. Do not run that next experiment.
5. Distinguish point-score leaders, conditional statistical evidence and an
   engineering recommendation; do not automatically promote NNUE. Original
   classical remains the active default.
6. Include interruption/resume fairness notes and final failure/termination
   counts. Previous NNUE games are background only, never pooled here.
7. Verify the completed resume starts no new searches, save final results,
   commit and push to `origin main`, and answer whether NNUE earned replacement.

Statistics: 12 paired opening units per match; conservative 95% Hoeffding bounds
and descriptive paired bootstrap; exact paired sign-flip two-sided tests with
Holm correction for the two candidates. One-sided NNUE p-values are descriptive.
Elo is a score-equivalent logit with wide/infinite bounds where appropriate.
The analysis also compares the candidates' scores on shared opening pairs.

Main commits before this pause: `5040524` scope README, `db1be62` verified frozen
setup, `353c06f` analysis, `4131378` first 12 games. Inspect the latest Git log for
the final pause checkpoint and do not reset/revert any existing files.
