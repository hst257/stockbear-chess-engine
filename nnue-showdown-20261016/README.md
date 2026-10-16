# NNUE architecture showdown

User-amended 108-game experiment: 72 games at 500 ms and 36 at 1000 ms.
The user requested a maximum of one second during the 1-second cohort.
No 3-second or 5-second games will be played. No extensions.
The original frozen 130-game plan is preserved for record identity;
`schedule-amendment.json` records the change. Use the amended entry point below.

All engines use the selected scaling-study checkpoints, float inference,
16 MiB hash, identical production search and `-O2` flags. Each has one search
thread, with pondering disabled. Only one game runs at a time. Fresh processes
reset game state; complete opening history preserves repetition rules.

Twelve established main lines are shuffled with seed 20261016. Nested prefixes
of 12/6 opening pairs are used at 500/1000 ms. Each pairing
plays both colors from exactly the same position. No Stockfish or evaluator
filter chooses openings. Candidates rank by the equal-weight mean
of the two retained per-format score fractions; tied groups use their head-to-head mini-league,
then smaller parameter count. No combined Elo estimate is calculated.

The deadline is requested movetime plus 100 ms of protocol/OS allowance.
Engine and wall times are recorded separately. Claimable threefold/50-move
draws are claimed automatically; automatic draws and terminal positions use
python-chess. A 400-searched-ply safety cap is unfinished/unscored, never a draw.
Failures save logs and halt, without assigning an automatic chess loss.

From `Z:\Code\Chess` in PowerShell:

```powershell
# After interruption, skip completed games and continue saved in-progress moves:
.\.venv\Scripts\python.exe -u -m tools.run_nnue_showdown_amended run
.\.venv\Scripts\python.exe -m tools.run_nnue_showdown_amended progress
.\.venv\Scripts\python.exe -m tools.report_nnue_showdown
```

`plan.json` freezes configurations, identities, openings and schedule.
`verification.json` records preflight/regressions. `games/Gxxx.json` is the
authoritative completed record; each game also has a PGN. Partial JSON saves
every searched move. `scoreboard.json` is updated after each game; `current.json`
shows a running game's progress. ETA uses measured game lengths and move
overhead, so it can change with format. Logs and isolated binaries live beneath
`artifacts/`. Source, binary, network and plan identities must match on resume.
The amended runner stops at G108 and starts no engines when already complete.
Do not invoke the original unbounded `tools.nnue_showdown run`: its retained
historical schedule includes the omitted controls.
The runner prevents system sleep only while its computation is active and
restores normal sleep behavior on exit; it does not change power settings.

No networks are trained, no labels regenerated, and the sealed test data,
classical evaluator and active installation are untouched.
