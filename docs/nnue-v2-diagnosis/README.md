# Compact v2 search diagnosis

This investigation freezes production behavior at `1b0894335bc50f10cbd5a44d1eb73840729c7516`.
It changes diagnostic tooling and optional instrumentation only. Classical remains the default.
The native float32 Compact v2 binary/model hashes and opening-book hash are in
`match-plan.json`; all earlier optimization records remain separate.

## Frozen tournament protocol

Exactly 190 scheduled games: 80 at 50ms, 60 at 200ms, 30 at 500ms and 20 at 1000ms
per searched move. Both players use the same preserved release executable, all
production search defaults, Hash=16MB, scalar NNUE kernel and incremental state.
Only `Evaluator` differs. One engine searches at a time. Each game resets state;
the engine also allocates fresh search tables for every move.

The fixed book contains 40 positions from 20 named opening families with seeded,
legal quiet continuations, without evaluation or outcome filtering. Longer controls
use the specified prefixes (30/15/10 pairs). Colors reverse within each pair.
Full cohorts are reported individually; cross-control trends use pairs 1–10 only.
The 500ms and 1000ms cohorts are exploratory. No additional games or optional
extensions are scheduled.

Rules: claimable threefold/fifty-move draws, normal terminal results, 240 searched
plies per game. Caps remain unfinished, never draws. If censoring becomes substantial,
report sensitivity and investigate the uniform cap protocol explicitly; do not
silently reclassify outcomes. Opening moves do not consume the searched-ply cap.
No evaluation-based adjudication or reference-engine assistance is used.

The first scheduled pair is the pilot, retained in the 80-game cohort. `pilot.json`
records a roughly 47-minute length-based estimate; the all-cap nominal upper workload
is 3.4 hours, excluding startup and communication. Later games may be longer.
Move wall time includes protocol/communication; reported engine time is kept separately.
Games checkpoint atomically; completed cohorts also have replayable PGNs.

```powershell
.\.venv\Scripts\python.exe -m tools.run_nnue_diagnosis_matches
```

The same command resumes checkpoints and verifies completed cohorts before skipping
them. Never overwrite finished results. Bootstrap sampling keeps both colors together;
related openings and small cohorts limit generalization. Capped pairs are excluded
from complete-pair inference, with censoring sensitivity reported separately.

## Remaining diagnostic protocol

Use a shared legal stratified FEN suite for equal-time, equal-node and equal-depth
searches, completed-iteration PVs and single-feature runtime ablations. Analyze
candidate moves offline with the local Stockfish 19, one thread, fixed node budgets,
fresh hash and consistent score perspective. Record mate values separately.
Counters/profiling must be explicitly compiled in and must not alter production
search or model contracts. Profiled throughput is not release throughput.
No network changes, retraining, search threshold tuning or lazy state implementation
are part of this investigation. Final findings: `NNUE_V2_SEARCH_DIAGNOSIS.md` at root.
