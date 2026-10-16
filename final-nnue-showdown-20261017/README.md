# Final classical versus NNUE showdown

Completed **48/48 games**. Classical scored 13–11 against 64/32 and 17.5–6.5
against 128/32. Keep classical as default; see `FINAL_NNUE_SHOWDOWN_REPORT.md`
at the repository root for uncertainty, performance, and the recommendation.

Exactly 48 games at 1000 ms per move: classical versus 64/32 (24 games),
then classical versus 128/32 (24). Both matches use the same 12 new opening
pairs with reversed colors, frozen before games and without evaluator filtering.
No extra games, training, labeling, or default-evaluator changes are authorized.

Reuse the previous verified `-O2` float32 binaries in isolated copies, with
identical production search options and 16 MiB hash. Classical explicitly
selects `Evaluator=classical`; startup probes and per-search counters must prove
NNUE is disabled. Its embedded but unused network is not a hybrid evaluation.

Games run serially, with fresh processes, full UCI history, automatic available
threefold/50-move claims, and python-chess terminal validation. Movetime has
the previous 100 ms wall allowance. A 400-searched-ply cap is unfinished and
unscored. Infrastructure failures checkpoint and halt without chess forfeits.

From `Z:\Code\Chess` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m tools.final_nnue_showdown prepare
.\.venv\Scripts\python.exe -m tools.final_nnue_showdown verify
.\.venv\Scripts\python.exe -u -m tools.final_nnue_showdown run --resume
.\.venv\Scripts\python.exe -m tools.final_nnue_showdown progress
.\.venv\Scripts\python.exe -m tools.report_final_nnue_showdown
```

`plan.json` freezes binaries, networks, options, openings, runner dependencies,
and the 48-game schedule. `games/` saves completed JSON/PGNs immediately and
partial move checkpoints for safe resume. Completed games are never replayed.
`scoreboard.json` and `current.json` track measured progress and ETA.
Build provenance, isolated binaries, and execution logs are in `artifacts/`.
Existing engines, models, prior studies, and sealed test data remain intact.
