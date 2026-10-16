# NNUE architecture showdown

Fixed 130-game experiment: 72 games at 500 ms, 36 at 1000 ms, 18 at
3000 ms, then four games between the two finalists at 5000 ms. No extensions.
The 3-second and 5-second cohorts are exploratory.

All engines use the selected scaling-study checkpoints, float inference,
16 MiB hash, identical production search and `-O2` flags. Each has one search
thread, with pondering disabled. Only one game runs at a time. Fresh processes
reset game state; complete opening history preserves repetition rules.

Twelve established main lines are shuffled with seed 20261016. Nested prefixes
of 12/6/3/2 opening pairs are used at increasing time controls. Each pairing
plays both colors from exactly the same position. No Stockfish or evaluator
filter chooses openings. Round-robin finalists rank by the equal-weight mean
of per-format score fractions; tied groups use their head-to-head mini-league,
then smaller parameter count. No combined Elo estimate is calculated.

The deadline is requested movetime plus 100 ms of protocol/OS allowance.
Engine and wall times are recorded separately. Claimable threefold/50-move
draws are claimed automatically; automatic draws and terminal positions use
python-chess. A 400-searched-ply safety cap is unfinished/unscored, never a draw.
Failures save logs and halt, without assigning an automatic chess loss.

From `Z:\Code\Chess` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m tools.nnue_showdown verify
.\.venv\Scripts\python.exe -u -m tools.nnue_showdown run
# After interruption, skip completed games and continue saved in-progress moves:
.\.venv\Scripts\python.exe -u -m tools.nnue_showdown run --resume
.\.venv\Scripts\python.exe -m tools.nnue_showdown progress
```

`plan.json` freezes configurations, identities, openings and schedule.
`verification.json` records preflight/regressions. `games/Gxxx.json` is the
authoritative completed record; each game also has a PGN. Partial JSON saves
every searched move. `scoreboard.json` is updated after each game; `current.json`
shows a running game's progress. ETA uses measured game lengths and move
overhead, so it can change with format. Logs and isolated binaries live beneath
`artifacts/`. Source, binary, network and plan identities must match on resume.
The runner prevents system sleep only while its computation is active and
restores normal sleep behavior on exit; it does not change power settings.

No networks are trained, no labels regenerated, and the sealed test data,
classical evaluator and active installation are untouched.
