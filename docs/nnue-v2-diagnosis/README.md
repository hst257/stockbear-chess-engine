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
Full-cohort summaries additionally resample named opening families as clusters,
because two variants of the same family may be correlated.
The all-ten trend also reports worst/best unknown-outcome bounds and joint
paired bootstrap sensitivity envelopes. Complete-case trends are supplementary;
capped pairs never silently disappear from the requested ten-pair comparison.
All capped final positions receive offline reference analysis. They remain
unfinished, and the reduced-runtime amendment rules out adding tournament games.

## Position and instrumentation protocol

Use a shared legal stratified FEN suite for equal-time, equal-node and equal-depth
searches, completed-iteration PVs and single-feature runtime ablations. Analyze
candidate moves offline with the local Stockfish 19, one thread, fixed node budgets,
fresh hash and consistent score perspective. Record mate values separately.
Counters/profiling must be explicitly compiled in and must not alter production
search or model contracts. Profiled throughput is not release throughput.
No network changes, retraining, search threshold tuning or lazy state implementation
are part of this investigation. Final findings: `NNUE_V2_SEARCH_DIAGNOSIS.md` at root.
Supplementary actual-game analysis selects one position per phase/control from
the first ten opening pairs, using the minimum seeded SHA256 key and legal/material
criteria only. The 12 positions receive paired 100k/400k-node searches and identical
SF300k child analysis, with complete pre-root move histories. Scores and outcomes
do not enter the sampling rule. This adds position analysis, not tournament games.

The position schedule is frozen in `positions.json`: 24 positions, three trials
at each of 50/200/1000ms, 25k/100k/400k nodes and depths 3/4/5. Ablations use
200ms and 100k nodes, two trials, changing one of LMR, null move, futility,
reverse futility or aspiration windows. No razoring, SEE quiescence pruning,
static-evaluation move ordering or cached TT static evaluations exist here.

```powershell
.\.venv\Scripts\python.exe -m tools.run_nnue_diagnosis_positions --phase all
```

This command resumes controlled searches, ablations and the independent SF19
child-analysis cache. Run it after tournaments, with no competing benchmarks.
Quality summaries use the first trial, with repeats reserved for speed and
stability; they are not counted as independent position samples. Root and child
SF searches each use 300k nodes, one thread, Hash64 and cleared hash. Direct
candidate child scores share the same context; raw root scores stay separate.

Optional builds use `tools/build_engine.py --diagnostics`, and additionally
`--profile` for exclusive clock scopes. Ordinary builds omit every new counter
and scope. `tools/profile_nnue_diagnosis.py` compares all three builds serially;
`tools/verify_nnue_diagnosis.py` checks preserved/rebuilt/counter/clock/UBSan trees,
trained goldens, the held-out corpus, accumulator transitions and UCI lifecycle.
Set `CHESSLAB_DIAGNOSTIC_ENGINE` when running the explicit depth-one counter oracle
in `tests/test_nnue_diagnosis.py`.

To run the bounded follow-up automatically after the match schedule:

```powershell
.\.venv\Scripts\python.exe -m tools.run_nnue_diagnosis_pipeline --wait-for-matches
```

This waits for all four JSON/PGN cohorts, then serially builds release, counter,
clock-profile and UBSan variants; runs the frozen position plan and reference
analysis; verifies native parity and the full test suite; exercises GUI workers;
and computes summaries/plots. The local training environment supplies matplotlib
for plotting only. Detailed stage logs remain in `artifacts/nnue-v2-diagnosis/`.
After a failure, fix its cause and resume, retaining completed experiment files;
use `--skip-builds` only when the recorded native sources and binaries still match.

Raw match-helper summaries retain a legacy limitations sentence mentioning its
old own-evaluator filter. That sentence does not describe this investigation:
the authoritative `opening_filter`, frozen book/source and book hash show that
no evaluator was queried to select openings. New analysis uses the actual protocol.

## Fresh reproduction

Preserve this directory. For a new run, set `STOCKBEAR_DIAGNOSIS_ROOT` to a fresh
results directory, `STOCKBEAR_DIAGNOSIS_ARTIFACTS` to a fresh build/log directory,
and `STOCKBEAR_DIAGNOSIS_ENGINE` to the Compact v2 release binary you built.
The new plan records that executable's actual hash; executable bytes can differ
across build paths/toolchains even when model bytes and fixed-budget trees agree.
The book/model and budgets remain fixed. `STOCKBEAR_DIAGNOSIS_PLOT_PYTHON` can
select a Python environment containing matplotlib. Run prepare, the first-pair
pilot, the fixed schedule, then the follow-up pipeline. The held-out SQLite
corpus, Stockfish 19 and training plot environment are local prerequisites for
the complete regression/reproduction workflow; they are not downloaded by it.
