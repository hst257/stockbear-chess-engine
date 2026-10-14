# Engine performance report

## Experiment and reproducibility

Original: `b5023bd`, ChessLab/StockBear 0.10, retained locally at
`artifacts/audit/original-b5023bd.exe`. Optimized: 0.11, milestone `17c66d9`,
frozen at `artifacts/audit/optimized-0.11.exe` and installed in
`engine/build/chesslab-engine.exe`. Both use portable C++17 **O2**, one search
worker, a 16 MiB Hash cap, and identical evaluation weights and selective-search
defaults. GUI time defaults remain 1 second. There are no new selective
heuristics, neural networks, books or tablebases.

Hardware: Intel Core i5-13420H, 12 logical CPUs, 31.7 GiB RAM; Windows,
Python 3.11.8, Zig 0.13.0/Clang. See [hardware](audit/hardware.json) and
[exact release flags](audit/final-build.json). CPU frequency/affinity were not
locked and background OS activity was not suppressed. Results describe this
machine/session, not a universal throughput guarantee.

The [baseline](audit/baseline.json) was frozen **before optimization** and never
overwritten: seven positions, depth 6 and 100/500/1000 ms, three samples per
cell, plus 26 canonical perft checks. Additional [paired measurements](audit/final-paired.json)
alternate executable order with five samples per cell. These additional original
samples do not replace the frozen baseline. Records retain hashes, configuration,
depth, nodes, Q nodes, time, NPS, score, best move, legal PV and available counters.

## Profiling and decisions

WPR was present and idle, but WPA/WPAExporter/Visual Studio analysis tools were
not found. No system-wide trace was started. A separate diagnostic executable
times exclusive scopes with `steady_clock` and counts search-thread C++
`new`/`new[]`. These are **instrumented wall-time estimates**, not OS CPU samples.
Clock overhead is substantial: opening NPS falls from about 2.6M release to
1.25M instrumented. Instrumented NPS is never used for release speed claims.

| Initial instrumented group | Share | Decision |
| --- | ---: | --- |
| Evaluation and subcomponents | 46.2% | Reuse fully keyed pawn-only information. |
| Other search/recursion/allocator/reporting | 23.6% | Remove recursive PV allocation; residual includes clock overhead. |
| Move generation | 14.0% | Short-circuit legal existence; generate captures only after Q stand pat. |
| Make/unmake | 7.6% | Already in-place with exact undo; retain it. |
| Draw checks | 3.1% | Correct two confirmed edge cases; retain terminal precedence. |
| Ordering | 3.0% | Replace allocating stable sort without changing ties. |
| TT | 1.3% | Preserve full-PV/context contract. |
| Search policy | 1.2% | Retain existing guards. |

[Before](audit/profile-before.json) and [after](audit/profile-after.json) include
raw scopes, calls, allocations and bytes. Instrumentation-only baseline nodes,
scores, moves and complete PVs match the original release. Initial evaluation
subgroups include pawn work 9.2%, attacks 5.4%, king safety 4.3%, endgame 4.3%,
PST walk 3.9%, and other evaluation 19.1%. Material/phase and mobility are in the
latter; not every instruction is separately attributed.

## Retained changes

1. **Bounded PVs and stable insertion ordering.** Recursive lines hold at most
   64 compact moves without clearing unused slots or allocating. Completed root
   results retain the public vector. TT entries retain full PVs. Insertion
   ordering preserves exactly the previous equal-priority order.
2. **Pawn cache.** A private 1024-entry table verifies both complete pawn
   bitboards, caching attacks/double control, pawn-only structure, passer masks
   and backward candidates. Blockage, kings, phase, shelter and feature selection
   remain live. Opening/middlegame/tactical hit rates at depth 6 are about
   48%/77%/90%; pawn endings exceed 96%.
3. **Less generation work.** Static leaves use the library's short-circuit
   legal-existence API. Ordinary non-check Q nodes establish a legal move and
   check terminal/draw conditions before stand pat, generating captures only if
   needed. Evasions, promotion-rank pawns and ordering-disabled Q retain the
   complete previous path. No move is selectively pruned.
4. **Rules fixes.** Same-color promoted bishop sets are insufficient material
   even above four occupied squares. Imported halfmove clocks above 100 saturate
   under the existing always-claim policy, avoiding the vendor's 8-bit overflow.
   [Audit details](engine-audit.md) explain histories and precedence. Vendor code
   remains unchanged.

`PawnCache` and `FastMovegen` independently default true in UCI. They change
implementation work, not evaluation formulas or search selectivity. All seven
frozen depth-6 score/node/move/PV snapshots and search counters remain identical.

## Before/after measurements

Five alternating-order samples; tables show median engine-reported time/NPS.
Short endings/terminal positions are excluded from fixed-depth speed claims
because millisecond timing is too coarse.

| Depth 6 | Nodes before → after | Seconds before → after | NPS before → after | Time change |
| --- | ---: | ---: | ---: | ---: |
| Opening | 203,811 → 203,811 | .078 → .055 | 2,612,961 → 3,705,654 | −29.5% |
| Middlegame | 378,976 → 378,976 | .162 → .104 | 2,339,358 → 3,644,000 | −35.8% |
| Tactical/Kiwipete | 553,706 → 553,706 | .218 → .137 | 2,539,935 → 4,041,649 | −37.2% |

| 1-second position | NPS before → after | NPS change | Median depth before → after |
| --- | ---: | ---: | ---: |
| Opening | 2,626,816 → 3,803,904 | +44.8% | 8 → 9 |
| Middlegame | 2,450,688 → 3,866,112 | +57.8% | 8 → 8 |
| Tactical/Kiwipete | 2,542,848 → 4,032,000 | +58.6% | 7 → 8 |
| Pawn endgame | 6,054,912 → 8,340,480 | +37.7% | 13 → 13 |
| Pawn zugzwang | 7,145,728 → 8,934,656 | +25.0% | 14 → 15 |

At 500 ms, median depth rises 7→8 in the opening/middlegame, 6→7 in the tactical
position, and 13→14 in zugzwang. Mate/stalemate still finish early. Timed scores
can differ because more work completes; deeper selective search does not
guarantee a better move in every position.

### Counters, middlegame depth 6

The original lacked evaluation/beta-cutoff counters. Its instrumentation-only
copy supplies those counts at the exact matching depth/node/score/PV; release
timings come exclusively from uninstrumented executables.

| Metric | Before | After | Change |
| --- | ---: | ---: | ---: |
| Evaluation calls | 320,647 | 320,647 | 0% |
| Q nodes | 359,045 | 359,045 | 0% |
| TT probes / hits | 18,916 / 5,252 | 18,916 / 5,252 | unchanged |
| TT hit rate | 27.76% | 27.76% | 0 pp |
| TT cutoffs | 3,202 | 3,202 | 0% |
| Bound cutoffs including Q stand pat | 271,638 | 271,638 | 0% |
| LMR searches | 4,039 | 4,039 | 0% |
| Null cutoffs | 202 | 202 | 0% |
| Aspiration retries | 0 | 0 | unchanged |
| Counted allocations | 255,751 | 89 | −99.97% |
| Counted bytes | 1,537,240 | 10,372 | −99.33% |
| Canonical perft cells | 26 pass | 26 pass | unchanged |

Tactical allocations fall 319,987→87; opening 70,868→89. Remaining counts include
root publication, reporting and initial history growth. TT/pawn-cache allocation
precedes the measured region. Direct malloc, aligned-new variants and exception
runtime internals are not comprehensively intercepted: this is not a claim of
zero process-wide heap allocation.

## Compiler experiments and deferred work

[O3](audit/04-o3.json), [O3/LTO](audit/05-o3-lto.json) and the decisive
[alternating comparison](audit/compiler-paired.json) are retained. At 500 ms,
O2 versus O3/LTO NPS is 3,795,968 versus 3,742,720 (opening), 3,828,224 versus
3,815,936 (middlegame), and 4,039,168 versus 4,034,560 (tactical). There is no
consistent gain justifying a new default. Portable O2 stays; selectable build
variants save exact flags to sidecars. Native-only instructions, PGO and unsafe
arithmetic options were not introduced.

Bitboards, magic sliders, attack tables and in-place undo already exist, so a
rewrite is unwarranted. Incremental material/PST/phase adds special-move coupling;
the profiled PST walk alone is about 4%, so finer attribution should precede it.
Compact/clustered TT entries require resolving full-PV storage for little
measured cost. Killer/history/SEE and further pruning change selective search
behavior and need separate strength studies; they remain absent.

Phase 7 was assessed and intentionally not implemented under its optional
conditions. The TT has non-atomic multiword entries and PVs; sharing it would
race. Lazy SMP also needs coherent stop/time/node accounting and completed-result
ownership. Twelve logical CPUs do not establish a strength-per-second gain.
Single-threaded reproducibility remains the default; SMP needs a separate
thread-safe design and scaling experiment.

## Verification and limitations

**929 automated tests pass.** UBSan passes 27,509 random real/null restoration
transitions, full histories, varied cached evaluation and bounded recursive
search. Tests cover published perft, independent tactical oracles, evaluation
symmetry/taper, TT bounds/history/collisions, PVS/aspiration/LMR/NMP safeguards,
stop/quit and stale replies. The audit distinguishes implemented features from
missing heuristics rather than treating a function's existence as proof.

The actual Pygame app with real UCI workers exercised all five presets. Dummy
driver render/update p99 times were 1.83–2.79 ms during play and 4.80 ms during
comparison; six recorded worker exits were zero. Undo/New rejected stale moves.
Minimum-size Search lab and a self-closing desktop-launch frame were visually
inspected. These are automated app checks plus a desktop launch, not an
interactive manual game. See [GUI evidence](audit/gui-verification.json).

Remaining measured cost is chiefly evaluation/attacks and recursive bookkeeping.
Instrumented shares are not CPU sampling. Future work: finer evaluation profiles,
held-out weight tuning, and independent strength experiments for new heuristics.
General dead-position solving beyond material patterns and exact pawn races
remain unsupported. A capped match reached a live rook-and-king versus king
ending without conversion; specialized endgame conversion is another limitation. ThreadSanitizer was not run on this Windows toolchain;
ownership was inspected and cancellation/stale-result tests passed.

## Match experiment

The experiment runs 200 games from 100 unique paired openings with alternating
colors, identical 50-ms move budgets and a 240-additional-ply cap. Seeded quiet
continuations of four named starts are filtered by original depth-3 evaluation
to |score|≤80 cp. This is heuristic opening balance, not an external oracle or
an engine opening book. Checkpoint/resume preserves completed games. The completed [JSON](audit/version-matches.json)
and [PGNs](audit/version-matches.pgn) identify both binaries and every opening,
move, completed depth, node count, NPS, time and score.

| Optimized outcome | Count |
| --- | ---: |
| Wins | 82 |
| Draws | 74 |
| Losses | 42 |
| Unfinished at cap | 2 |

Score on 198 completed games is **60.10%**, giving a logistic rating-difference
estimate of **+71.2 Elo** for this experiment. Pair uncertainty uses the 98 fully
completed opening pairs (both capped pairs are excluded): paired score 59.95%,
nominal conservative 95% bounded-score interval **46.23–73.67%**, or approximately
**−26.2 to +178.7 Elo**. The Hoeffding interval keeps both colors together and
assumes independent opening pairs. Its width is intentional; the interval
includes zero, so this run does **not** establish a statistically conclusive
strength gain or a universal Elo rating. The fast budget, heuristic opening
filter, OS scheduling and capped games limit generalization.

The two live caps are rook-and-king versus king (game 51) and rook-and-king
versus rook-and-king (174). They are never silently counted as draws. Treating
both caps as losses or wins gives an all-200-game score range of 59.5–60.5%.
The point estimate uses all completed games; the confidence bound uses complete
pairs, explaining its slightly different center. The harness takes available
python-chess draw claims consistently for both sides.

A transient Windows checkpoint-open error stopped the runner after 178 saved
games. Atomic temporary-file replacement and bounded retries were added and
tested; the intact checkpoint resumed with identical binaries/time/openings.
No engine crashed and no saved game was discarded. All **200 PGNs** were then
independently replayed: **24,392 legal plies**, unique paired openings, results,
and both executable hashes verified. See [replay/correctness evidence](audit/replay-verification.json).

## Phase completion

| Phase | Result |
| --- | --- |
| 1 — Audit | Architecture, feature statuses, evaluation, UCI/GUI and rules inspected and tested. |
| 2 — Baseline | Original executable retained; immutable tests/perft/tactical/depth/time records saved. |
| 3 — Profile | Explicit exclusive timing/allocation evidence with overhead and sampling limitations stated. |
| 4 — Optimize | Three measured implementation optimizations and two confirmed rules fixes retained; compiler variants assessed. |
| 5 — Compare | Incremental records and five-sample alternating final comparison saved. |
| 6 — Strength | 200 paired-color games, PGNs, score and conservative rating uncertainty recorded. |
| 7 — Optional SMP | Assessed and deliberately deferred under the brief's thread-safety/evidence conditions. |
| 8 — Report | This report, the feature audit, raw measurements and reproduction commands completed. |

## Reproduce

Run from the repository root with the pinned dependencies installed. Frozen
reports refuse overwrite; choose a new artifact path for each local experiment.

```powershell
.\.venv\Scripts\python.exe tools/build_engine.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/build_engine.py --profile --output artifacts\audit\local-profile.exe
.\.venv\Scripts\python.exe -m tools.audit_engine --engine artifacts\audit\local-profile.exe --times --repeats 1 --output artifacts\audit\local-profile.json
.\.venv\Scripts\python.exe -m tools.compare_engine_versions --engines original=artifacts/audit/original-b5023bd.exe optimized=engine/build/chesslab-engine.exe --output artifacts\audit\local-paired.json
.\.venv\Scripts\python.exe -m tools.match_optimizations --comparison versions --engine engine/build/chesslab-engine.exe --opponent artifacts/audit/original-b5023bd.exe --games 200 --movetime 50 --max-plies 240 --output artifacts\audit\local-matches.json
.\.venv\Scripts\python.exe -m tools.verify_gui_engine
.\.venv\Scripts\python.exe tools/build_engine.py --target audit-tests --sanitize undefined --output artifacts\audit\local-ubsan.exe
.\artifacts\audit\local-ubsan.exe
```

For a fresh clone without the preserved executable, build source `b5023bd` in
an isolated checkout; do not reset a working checkout with uncommitted changes:

```powershell
git worktree add --detach artifacts/audit/original-source b5023bd
.\.venv\Scripts\python.exe artifacts/audit/original-source/tools/build_engine.py
```

Use that checkout's `engine/build/chesslab-engine.exe` as the opponent. Rebuilt
hashes may differ with paths/toolchains, so record fresh metadata. Add `--resume`
to the same match command after an interrupted run; executable hashes, game
count, time and cap must match its checkpoint. `--optimization O3 --lto` builds
the rejected compiler variant; default builds remain O2. No recurring automation
or background service is required.
