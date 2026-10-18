# Tournament 2 complete

All **80/80** official games are complete; none remain. Read STOCKBEAR_GRAND_FINAL_REPORT.md, STOCKBEAR_FINAL_CHAMPION.json and completion.json. No additional games are authorized.

The user-requested 67-game pause and manual continuation are documented in pause-audit.json and resume-audit.json; PAUSED.md and pause-manifest.json are historical snapshots. No engine/default/model was changed or promoted.

To audit the saved outputs without starting engines:

```powershell
.\.venv\Scripts\python.exe .\stockbear-final-tournament-2-20261017\final_audit.py
```

## Historical standalone execution commands

The commands below describe the frozen runner. A completed resume skips all80 games and starts no searches.

# Tournament 2: Classical versus Hiddenclip

Exactly80 official games,40 reversed opening pairs,500ms/move. Production engines,
model weights and previous studies are preserved. Production defaults are not changed.

From `Z:\Code\Chess`, Windows PowerShell:

```powershell
# Already prepared and preflight-verified for this frozen experiment:
.\stockbear-final-tournament-2-20261017\start_tournament.ps1

# Read progress (no engines started and no results rewritten):
.\.venv\Scripts\python.exe .\stockbear-final-tournament-2-20261017\tournament.py status
Get-Content -LiteralPath ((Get-Content .\stockbear-final-tournament-2-20261017\runner-pid.json -Raw | ConvertFrom-Json).stdout) -Tail 8

# Restart after interruption; skips completed games and restores saved moves:
.\stockbear-final-tournament-2-20261017\start_tournament.ps1 -Resume

# Foreground alternative, interrupt with Ctrl+C:
.\.venv\Scripts\python.exe -u .\stockbear-final-tournament-2-20261017\tournament.py run --resume

# Recreate derived results/report/handoff only after all80 games finish:
.\.venv\Scripts\python.exe .\stockbear-final-tournament-2-20261017\tournament.py analyze

# After the runner exits, audit every saved PGN/export and refresh the manifest:
.\.venv\Scripts\python.exe .\stockbear-final-tournament-2-20261017\final_audit.py
```

No dependency installation or engine build is needed: the existing Python venv,
python-chess, exact EXEs and prior provenance are required. Missing or changed
identities cause a hard stop; no silent substitution/rebuild. `freeze` and
`preflight` are setup commands, never rerun them over an active official study.

The hidden standalone process can continue after the Codex turn ends. It requests
temporary prevention of idle sleep without changing Windows power settings; the
request is released at exit. Keep AC connected and power/NitroSense settings
unchanged. A machine restart still interrupts execution; use `-Resume` afterward.

Each legal move is transactionally checkpointed. Completed JSON is committed only
after full legal replay and PGN validation. OS locking prevents two writers.
Partial checkpoints and protocol logs are retained after completion; nothing is
deleted. Resume resets both engines/TT, preserves full game history, and records
the restart. Technical failures halt unscored for investigation, retaining full
logs. Do not erase errors or replay an unfavorable completed game.

The runner automatically performs final validation, paired statistics, report and
`STOCKBEAR_FINAL_CHAMPION.json` creation after game80; Codex need not issue moves or
remain connected. No extra games, cleanup or promotion follow. Detailed per-game engine
logs append and game/event checkpoints remain authoritative. Each launch has separate timestamped stdout and
stderr files under `run-logs/`; earlier wrapper logs are preserved as well.
