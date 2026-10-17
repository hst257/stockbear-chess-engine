# Tournament 2 — paused at user request

Exactly **67/80** official games are complete. The user requested a stop after two more games when65 were complete; games66 and67 finished, then the stop marker halted the runner before any game68 search. **13 games remain.** No automatic resume is scheduled.

Interim points: Hiddenclip **35.0/67**, Classical **32.0/67**. This incomplete, unbalanced-pair tally is not a final strength result. No champion or final report has been fabricated.

All67 records and PGNs legally replayed; all frozen gameplay/report source hashes and protected artifacts match. The game68 partial checkpoint contains **zero** searched moves; both engines were initialized but received no go command. The expected KeyboardInterrupt in the runner error log is the requested stop, not an engine failure. Full logs/checkpoints are retained.

To manually continue the remaining frozen schedule from Z:\Code\Chess:

```powershell
.\stockbear-final-tournament-2-20261017\resume_tournament.ps1
```

The wrapper clears only the pause marker, then resumes. Completed games are skipped. Keep AC connected and the same profile/power settings. The untouched frozen runner will automatically generate the final analysis/report/handoff only after all80 games. Then run final_audit.py and commit/push the completed evidence. No extra games, production changes, cleanup, training or labeling.
