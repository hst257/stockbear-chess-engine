# Aspiration windows, null-move pruning, and LMR

All three are enabled by default in the C++ engine. They were implemented and
validated sequentially: aspiration alone, then null-move pruning, then LMR.
The Python/Pygame layout, five time presets, evaluator, move generator, existing
ordering, and UCI worker remain in place. Minimax ignores all three optimizations.

## Aspiration windows: smaller root windows

The first iterative pass uses a full window. Later passes center a window on the
previous completed White-relative score, initially ±25 centipawns. A narrow
window can establish cutoffs sooner when the score stays nearby. A fail-low or
fail-high is only a bound: the failed side's margin doubles and the pass retries.
The opposite bound remains unchanged. Margins are clamped; after 16 failures or
a near-mate result the retry uses a full window. Previous near-mate scores also
start with a full window. Direct search and Minimax skip aspiration.

Only a successful exact pass commits its move, score, and PV. A deadline or stop
during retries retains the previous completed iteration. Retries share its time,
node budget, TT, and previous-PV hints. Existing TT bound types remain meaningful:
a failed root window never becomes an exact published score.

## Null-move pruning: a hypothetical pass

At a suitable non-PV node, the engine tests skipping a turn at reduced depth
`depth - 1 - R`, with **R=2**, using a unit-width window. White tests its beta
bound; Black tests its alpha bound because evaluation remains White-relative.
If even that hypothetical pass meets the bound, the real node can cut off.

The pinned rules library already provides make/unmake null moves. `ScopedNullMove`
wraps them for exception-safe restoration: side and Zobrist change, en passant
clears, pieces/castling/real halfmove count stay intact, and unmake restores the
exact prior state. Null moves never enter gameplay PVs or bestmove output.

Conservative eligibility requires all of:

- Alpha-beta, depth ≥3, a non-root **unit-window non-PV** node, and no check.
- At least two non-pawn, non-king pieces for **each** side; material phase ≥8.
- Halfmove clock below 90, no current repeated position, and no near-mate bound.
- No existing null subtree; nesting is disabled throughout a hypothetical branch.
- Static evaluation already meets the tested bound.

Pawn-only endgames and many sparse zugzwangs therefore bypass NMP. Zugzwang is
dangerous because being forced to move can worsen a position, invalidating the
pass assumption. These guards reduce risk, not prove the heuristic sound.
Null subtrees neither probe nor store the normal TT, and suppress repetition and
fifty-move adjudication against artificial history. Insufficient material and
mate/stalemate remain checked. Null-inferred mate scores cannot cause cutoffs.
A null cutoff returns only the window edge and stores no node/PV of its own.

## LMR: reduce unpromising late quiet moves

After the first **four** moves, a quiet move may be searched one ply shallower.
The initial reduction is **1**; UCI tuning allows 1–3, clamped to `depth - 2`, so
at least one main-search ply remains in the reduced child. There is no adaptive
logarithmic table in this version.

LMR requires alpha-beta, existing move ordering, depth ≥3, a non-root unit-window
non-PV node, material phase ≥4, and ordinary non-mate bounds. It excludes check
evasions, captures (including EP), promotions, castling, direct/discovered checks,
TT moves, previous-PV hints, and every hypothetical null branch. The first four
moves and PV nodes keep nominal depth. With ordering off it uses the full-depth
fallback. No killer/history ordering was added; existing TT/PV/promotion/MVV-LVA
ordering remains the source of priorities.

An unexpected bound improvement gets **full nominal-depth verification** using
the scout window. An enclosing PVS node performs its wider re-search if needed;
LMR does not duplicate that wider search. Fail-low reduced moves can be discarded
without full verification. This selectivity can miss quiet tactical resources.

## Interaction, bounds, and cancellation

Aspiration changes root windows; PVS supplies narrow scouts where NMP/LMR become
eligible. This conservative implementation disables both selective methods at
wide-window PV nodes; disabling PVS generally leaves them inactive. Aspiration
alone preserves exhaustive fixed-depth scores. NMP and LMR may change them.

TT score reuse still checks depth, legal moves, draw context, and Q extension
allowance. Reduced calls store their actual reduced depth; the nominal parent
classifies its returned score against its original window. An EXACT tag with
selective search enabled does not imply an exhaustive full-width proof.
Tables are fresh per go, isolating configuration changes. Interrupted nodes never
reach storage; temporary real and null moves unwind through RAII.

All work shares the existing steady-clock deadline, recursive 256-node clock
checks, atomic stop flag, and last-completed snapshot. Python retains revision and
request-token checks; progress cannot play a move. No new search threads or
process restarts between iterations were introduced.

## Configuration and diagnostics

```text
setoption name UseAspirationWindows value false
setoption name UseNullMovePruning value false
setoption name UseLMR value false
setoption name AspirationDelta value 25
setoption name LMRReduction value 1
position startpos
go depth 5
```

The three check options default true. AspirationDelta defaults 25 (range 1–500 cp);
LMRReduction defaults 1 (range 1–3). Python configuration uses corresponding
EngineSettings fields; the launcher provides independent switches:

```powershell
.\launch.bat --mode engine --no-aspiration-windows
.\launch.bat --mode engine --no-null-move-pruning --no-lmr
.\launch.bat --mode engine --search-mode depth --depth 5 --no-aspiration-windows --no-null-move-pruning --no-lmr
```

There is no dedicated advanced GUI settings area, so no new gameplay controls
were added. Search lab retains its normal statistics; selective results can differ
from Minimax even at the same nominal depth. Use the off switches for exact
full-width comparisons.

UCI-safe `info string optim` messages and final summaries report cumulative:
aspiration_attempts/searches/fail_high/fail_low/retries/successes,
null_attempts/cutoffs, and lmr_attempts/searches/researches/verifications.
Aspiration attempts count started narrow-window iterations; searches include
retry invocations, and successes count committed iterations even after a full
window fallback. LMR attempts equal reduced searches, and re-searches equal
full-depth verifications in this initial policy. Nodes/time include all retries,
null branches, reduced searches, and verification work, including unfinished work.

## Reproduce measurements

```powershell
.\build_engine.bat
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tools.benchmark_optimizations --stage 3 --depth 5 --output artifacts\optimization-benchmark.json
.\.venv\Scripts\python.exe -m tools.match_optimizations --games 4 --movetime 100 --output artifacts\optimization-matches.json
```

Stages are baseline (all off), aspiration only, aspiration + NMP, and all three.
The benchmark uses identical FENs, evaluator, ordering, PVS, Q, TT (Hash=16 MiB),
and a single initialized UCI process. It records fixed-depth 5 plus each of
100/500/1000/3000/5000 ms, best move, White score, completed depth, nodes, time,
NPS, legal PVs, feature counters, platform, SHA-256, and raw samples. A fixed-depth
15-second watchdog detects unfinished measurements; timed watchdogs allow OS
and communication overhead. Repeats can be increased with `--repeats 3`.

Independent stage evidence: [aspiration](optimization-stages/stage1.json) and
[null move](optimization-stages/stage2.json), captured before implementing the
next algorithm. Each file identifies its own intermediate binary SHA-256.
Earlier PST/TT/Q/time benchmarks explicitly disable all three new features to
preserve their historical conditions.

## Recorded performance and regressions

The [final raw benchmark](optimization-benchmark.json) contains **168 measurements**
(seven positions × four stages × six limits), one sample per combination. Raw
engine time, wall time, NPS, evaluations, PVs, and every diagnostic counter are
retained. Timings vary with CPU load; fixed-depth node counts are deterministic.

Depth-5 nodes (PST/Q/PVS/ordering/TT enabled in every stage):

| Position | Baseline | Aspiration | + NMP | + LMR | Final change |
| --- | ---: | ---: | ---: | ---: | --- |
| opening | 49,994 | 47,341 | 35,631 | 10,405 | 79.2% fewer |
| middlegame | 222,656 | 221,157 | 139,064 | 88,463 | 60.3% fewer |
| tactical | 349,872 | 326,722 | 478,814 | 355,317 | 1.6% more |
| endgame | 1,995 | 1,987 | 1,987 | 1,987 | 0.4% fewer |
| zugzwang | 241 | 241 | 241 | 241 | 0.0% fewer |

All depth-5 stage pairs in this sample returned the same move and score: Nc3/+40,
Bg5/+10, dxe6/+40, Ke5/+65, Ke5/+150, Qg7#/mate-in-one, and stalemate/0.
This is measured agreement, not a general equivalence claim for NMP/LMR.
NMP alone increased tactical-position nodes from 326,722 to 478,814 versus
aspiration only; LMR recovered much of that cost, but the final tactical tree
still exceeds baseline by 1.6%. Sparse endings bypass NMP/LMR and see little change.

Opening completed depths under each fixed time budget:

| Budget | Baseline | Aspiration | + NMP | + LMR |
| --- | ---: | ---: | ---: | ---: |
| 100 ms | 6 | 6 | 6 | 7 |
| 500 ms | 6 | 7 | 8 | 8 |
| 1000 ms | 7 | 7 | 8 | 9 |
| 3000 ms | 8 | 8 | 9 | 10 |
| 5000 ms | 8 | 8 | 9 | 10 |

The final depth-5 opening search recorded 7 aspiration retries, 85 null probes/75 cutoffs, and 246 reduced searches/0 full-depth verifications.

At five seconds the tactical position reached depth 9 with all features versus
baseline depth 8, but the deeper White score changed from +25 to −25 cp. More
depth is not a promise of a better move. Some equal-depth/endgame timing pairs
also differ because elapsed budgets expose scheduling and checkpoint boundaries.
No correctness regression was detected in the tested rules/tactical suite.

## Validation evidence

**773 tests pass on Windows.** The independently completed stages passed 617
(aspiration) and 631 (NMP) tests before the next implementation began. LMR and
combined focused tests then passed before the full 773-test run.

Coverage includes full-window aspiration equivalence across Q/PVS/TT modes,
fail-low/high and interrupted retries, native real/null exception unwinding,
Zobrist/EP/castling/clock/history restoration, protected pawn zugzwangs, check and
mate guards, LMR tactical/TT/PV exclusions and reduction clamps, real full-depth
verifications for both colors, deterministic toggle combinations with both
material/PST and Q modes, Minimax unchanged, repeated/fifty-move draws,
selective node-budget interruption, UCI validity/options/stop/quit, and stale
GUI replies. Tactical regressions include a quiet king move forcing mate and
the Opera Game's Qb8+! queen sacrifice. Real-engine Pygame checks at 1100×760
and 960×680 verified responsive play (depth 9), comparison, Undo/New Game,
stale-reply rejection, and rendered panels. The native Windows app launched,
but desktop automation twice failed with `failed to activate captured window`;
no new native-interaction verification is claimed. The real-engine checks used
SDL's dummy driver; prior native desktop checks remain historical evidence.

## Color-balanced smoke games

The [match record](optimization-matches.json) and [complete PGNs](optimization-matches.pgn)
compare baseline against all three optimizations, **100 ms per move**, alternating
colors from the initial position and a six-ply Italian opening. Each game allows
160 additional plies; available draws are claimed consistently.

| Game | Advanced color | Opening | Result for advanced | Ending |
| --- | --- | --- | --- | --- |
| 1 | white | Initial | win | checkmate |
| 2 | black | Initial | draw | threefold_repetition |
| 3 | white | Italian | unfinished | ply cap (unfinished) |
| 4 | black | Italian | win | checkmate |

The sample gives **2 wins, 1 draw, and 1 unfinished game** for the advanced
configuration. The capped game is not counted as a draw. This is a smoke check,
not reliable evidence of Elo gain or universal stronger play. Run many more
paired games/openings before tuning or claiming strength improvements.

## Changed modules

| Area | Files and purpose |
| --- | --- |
| C++ | `search.cpp/.hpp`: windows, selective search, counters; `search_policy.hpp`: eligibility; `scoped_move.hpp`: null restoration; `main.cpp`: UCI options/diagnostics |
| Python | `app/engine_client.py`, `app/main.py`: independent configuration without layout changes |
| Tests | Optimization matrix, native guards/restoration, UCI cancellation/options, unchanged legacy baselines |
| Measurements | `tools/benchmark_optimizations.py`, `tools/match_optimizations.py`, historical benchmark switches, recorded JSON/PGNs |

## Limits and next step

No performance or strength improvement is universal. Aspiration retries, null
probes, sorting, and verification can add work. NMP/LMR are selective heuristics,
not correctness-preserving replacements for exhaustive search. The material/draw
and tactical guards are conservative, not a complete zugzwang or mate-threat
oracle. Existing Q caps and claimable-draw policy remain unchanged. Linux desktop
behavior remains unverified.

The smoke match sample is too small for reliable Elo conclusions; capped games
must remain marked unfinished. Run larger color-balanced matches before tuning
thresholds. Killer/history quiet-move ordering is a reasonable next code upgrade,
but is not implemented in this change.
