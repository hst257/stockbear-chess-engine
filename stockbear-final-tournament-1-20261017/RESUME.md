# Completed Tournament 1

All 80 official games are complete. Hiddenclip scored 42/80 versus Stage 1's
38/80 (32 wins, 20 draws, 28 losses from hiddenclip's perspective). The paired
95% score interval includes 50%, so hiddenclip is the practical Rule B finalist,
with no statistically established superiority. See the report and handoff.
Do not run additional games or Tournament 2.

The game runner's postprocessing import collision was repaired after game 80;
original executed source and its hashes are retained under `provenance/` and
`harness-recovery.json`. No completed game was replayed. The notes below preserve
the original startup/recovery context; current result files take precedence.

The official frozen80-game tournament was launched successfully on17October2026
at21:00IST. Check `progress.json` and `runner-pid.json` for live state; these are
authoritative rather than this note. Original host launcher PID was22692. A
sandboxed process query could not see it, but host verification showed it was
healthy; no second runner was launched and no game was interrupted by that check.

Do not rerun `freeze`, preflight, smoke games or completed official games. Do not
change openings, schedule, time controls, engines, model or selection rules. Do
not start Tournament2 or clean up files. Both exact preserved engines useclip,
NNUE evaluator, CPU0,16MiB hash and500ms/move. Exactly40 color-reversed pairs.

The runner operates independently and automatically creates the final report,
CSVs, PGN, paired statistics, manifest and `TOURNAMENT_1_FINALIST.json` after80
games. `README.md` has start/status/resume commands. Use host process visibility
when checking the PID; sandbox `Get-Process` alone can falsely suggest absence.
The lock and creation-time PID guard prevent duplicate workers. Resume only if
the actual host runner has stopped, preserving all completed and partial games.

At completion, inspect the report and errors, verify all80 games/40 reversed
pairs and parseable PGNs, inspect paired confidence and exact ruleA/B/C/D
selection, and verify original hashes/protected files. All new artifacts stay in
this workspace. Code/config changes have not been made to the active engine.

Publish in **one final commit**, then push `codex/nnue-tournament-1` toorigin,
following the user's standing authorization. No interim commits are necessary.
The actual original engines, models, prior studies and losing implementation
must remain preserved. Do not promote a production evaluator.
