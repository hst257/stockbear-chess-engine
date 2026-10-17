# StockBear — Stage 2 accumulator optimization report

## Decision and scope

**INCONCLUSIVE overall — retain Stage 1 as the experimental baseline.**
No Stage 2 candidate is accepted; retain Stage 1 as the winner.
Three independent trials completed **2,880 primary searches**.
All numerical and fixed-work correctness gates pass. The detailed comparison below is
against the accepted **Stage 1 `NNUEKernel=clip`**, never the old scalar head.
The independent trials change maintenance only; they do not change the model,
persisted accumulator-frame layout, floating arithmetic or search policy. The detailed
per-fixture table uses the selected primary trial; all trials are summarized below.

Branch: `codex/nnue-stage2-accumulator`, based on Stage 1
`f397a5af002900bbc15a7261dc6027c48daaeff4`. The active engine and classical default are
unchanged. No training, labeling, tournaments, sealed-test access, promotion,
lazy updates, quantization or Stage 3 work took place.

## Independent trial summary

| Trial | Passes | 200k | 1M | 100 ms | 500 ms | 1000 ms | Status |
|---|---:|---:|---:|---:|---:|---:|---|
| tiny-list sort specialization | 10 | 1.0275x [1.0082, 1.0387] | 1.0275x [1.0066, 1.0456] | 1.0322x [1.0103, 1.0563] | 1.0282x [1.0011, 1.0509] | 1.0278x [1.0079, 1.0408] | INCONCLUSIVE |
| ordered parent-copy/row fusion | 7 | 0.9929x [0.9742, 1.0065] | 0.9865x [0.9695, 1.0055] | 0.9891x [0.9663, 1.0285] | 0.9825x [0.9718, 0.9969] | 0.9805x [0.9668, 0.9912] | REJECTED |
| small search-state temporary specialization | 7 | 0.9798x [0.9685, 0.9976] | 0.9856x [0.9728, 0.9945] | 0.9821x [0.9660, 0.9990] | 0.9852x [0.9745, 0.9989] | 0.9845x [0.9755, 0.9960] | REJECTED |

Brackets are grouped 95% intervals. Every trial has its own paired Stage 1 controls; do not compare absolute NPS between sequential trials as a matched experiment. All complete per-position results are in `per-position-sort.csv`, `per-position-fused.csv` and `per-position-small.csv`.

* **sort**: 1200 measured searches; 1 material fixture/control medians.
* **fused**: 840 measured searches; 12 material fixture/control medians.
* **small**: 840 measured searches; 11 material fixture/control medians.

| Trial | Quiet update speedup | Capture | Promotion | Mixed (null-heavy) |
|---|---:|---:|---:|---:|
| sort | 1.074x | 1.027x | 1.167x | 1.255x |
| fused | 0.930x | 0.887x | 0.835x | 0.900x |
| small | 1.024x | 0.973x | 1.050x | 1.080x |

| Correctness trial | Legal / null oracle | Head bit checks | Exact fixed-work fixtures/controls | Cancellation cases |
|---|---:|---:|---:|---:|
| sort | 31,876 / 26,908 | 161,420 | 36 | 24 |
| fused | 31,876 / 26,908 | 161,420 | 36 | 24 |
| small | 31,876 / 26,908 | 161,420 | 36 | 24 |

The sort trial reached the predeclared ten-pass ceiling because its seven-pass intervals crossed no gain. All five intervals then became positive, but promotion at 1M nodes remained 3.11% slower in elapsed time, leaving it inconclusive. The interrupted resume runner had skipped searches but redundantly written checkpoints for already completed rows; that bug was fixed. Original raw load segments are retained; duplicate empty resume segments are excluded from analysis. No measured searches were replayed. `plan.baseline_commit` is the authoritative Stage 1 revision; the inherited `source_revision` in this frozen initial plan refers to the older Stage 1 setup commit, not the measured baseline binary.

## Baseline and reproducibility

* Baseline: exact copied Stage 1 binary, SHA-256
  `e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d`; independently reconfirmed before changes.
* Candidate: `nnue-optimization-stage2-20261017/artifacts/sort/engine.exe`, SHA-256
  `9993433e680823c439dbb0b6234244ffab29792af2aeb2eeda9af1ce358d599d`. Each has its matching local PDB.
* Target: existing NNUE 64/32, 54,209 parameters; selected `medium/best.pt`
  and `medium.sbnnue` remain hashed and unchanged. Export SHA-256
  `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`. No fresh export or weights were generated.
  Checkpoint SHA-256: `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`.
* Same Zig 0.13 / Clang 18 toolchain, C++17, `-O2 -pthread -Wall -Wextra
  -ffp-contract=off`, baseline update strategy **2**, primary candidate **2**; no fast-math or LTO
  flag was added. Full commands and all source/header hashes are saved.
* One search thread, 16 MiB TT, CPU-0 affinity, `NNUEKernel=clip`, identical
  options, 12 frozen positions including full opening history, fresh TT per go.
  10 paired, rotated passes; 1200 primary searches. Per-position
  records retain wall time, reported NPS, depth, seldepth, moves, scores, PVs,
  all search counters, evaluation calls and quiescence counts.

Power/environment: AC was measured online; Windows Acer power scheme and last
user-confirmed NitroSense Quiet/Eco profile were retained. NitroSense is not
readable through the power-plan setting, so its current mode is not independently
verified. No settings/apps were changed. All CPU-intensive work ran serially.
Background CPU after subtracting benchmark processes: median
10.13%, range
5.30–23.99%
of total logical-CPU capacity. This is not CPU-0 contention or temperature.
Thermal/throttle, cache-miss, branch-miss and cycle counters were unavailable.

## Accumulator pipeline audit

Roots refresh once; children use legal move deltas captured before make-move,
then cleaned rights/legal-EP state extracted after the move. White/Black float
lanes remain unclipped in fixed storage order. Changes are applied in ascending
absolute feature order with one separate float add/subtract per row. Null moves
still clear legal EP state and receive distinct child storage. Parent/sibling
frames are never shared mutably.

The generic frame is 1,176 bytes (512 float-lane bytes, 512 unused integer-lane
bytes in this kernel, 152 feature bytes). The 65-frame stack is 76,440 bytes,
allocated once per search and reused by ply. Compact children retain only state
metadata, although roots and generic APIs retain full features. Only needed
metadata and float lanes are copied; allocation size is not bytes copied/node.
No root-refresh excess, king-triggered refresh or per-head allocation was found.
The allocation observer starts inside search after TT construction; it cannot
measure all process allocations. It recorded 4,059 allocations /
3,268,856 requested bytes across 36 instrumented searches.

Fresh Stage 1 clip counters: 7,192,359 updates / 7,200,000 nodes,
0.998939 updates/node,
2.32556 changed rows/perspective,
518.652 logical bytes copied/child,
0.317% null updates, exactly one refresh/search.
Logical bytes are not measured cache traffic.

### Maintenance costs and observer limits

| Isolated timer category | Calls (36 searches) | Total ms | ns/update | ns/node | % timer sum |
|---|---:|---:|---:|---:|---:|
| nnue_copy | 14,384,718 | 436.28 | 60.658 | 60.594 | 3.816 |
| nnue_rows | 14,384,718 | 578.96 | 80.496 | 80.411 | 5.064 |
| nnue_sort | 21,577,077 | 681.26 | 94.719 | 94.619 | 5.958 |
| nnue_metadata | 14,384,718 | 425.35 | 59.139 | 59.076 | 3.720 |
| nnue_delta | 7,169,589 | 215.31 | 29.936 | 29.904 | 1.883 |
| nnue_state | 7,192,359 | 222.68 | 30.961 | 30.928 | 1.948 |
| nnue_ep | 17,364 | 1.79 | 0.249 | 0.249 | 0.016 |
| nnue_update | 7,192,359 | 2165.80 | 301.125 | 300.805 | 18.943 |
| nnue_refresh | 36 | 0.10 | 0.015 | 0.015 | 0.001 |

`nnue_update` is exclusive residual bookkeeping, not inclusive update latency.
Sorting covers two tiny state lists and both changed-row lists; `nnue_state`
excludes its nested EP scope. Row cost includes two perspective scopes; divided
by actual rows it is an **instrumented amortization**, not pure instruction cost.
Copying/state/metadata values near the clock floor cannot be ranked precisely.
Feature indexing is in `nnue_delta`; null counts are logical counter events and
their actual path is separately exercised by microbenchmarks below.

Counter-only median elapsed overhead was
1.055x; detailed timers
3.201x (per-position range
2.49–3.98x).
All observer fixed-work decisions/counters match baseline. **Timer totals are
perturbed costs, not production nanoseconds or an Amdahl forecast.**

The verified earlier native trace uses the exact Stage 1 binary: 4,069 samples,
32.37% head, 19.32% narrowly recognized maintenance. Most recognized maintenance
is inlined into descent; generic row/state sorting alone has about 2.43% of
samples, overlapping that classification. These shares must not be added.
It cannot reliably rank all inlined maintenance suboperations. Taken together,
the evidence points to repeated bookkeeping/tiny sorts as a useful addressable
cost; a claim that exact production sorting cycles exceed row arithmetic would
be unsupported. Full refresh and rare EP legality checks are poor first targets.

## Candidate and exact changes

The sort trial's `sort.patch` adds the include for `small_sort.hpp` and replaces only the compact updater's state
and signed-row `std::sort` calls with insertion sorting for tiny lists. States
have at most five keys; changed rows have at most sixteen storage slots. Legal
orthodox deltas have unique absolute feature keys, so the resulting row sequence
is identical. A separate 17,000-case ordering check covers lengths 0–16.
The row-fusion trial selects the already existing strategy **4**, independently
from baseline source. For 2/3/4 changed rows, each lane starts from the parent,
applies every sorted row separately in original order, then stores once.
Other row counts use the original copy/row loops. The small-state trial
selects existing strategy **5**: only the temporary returned and
copied by state extraction shrinks, from 152 to 24 bytes. It does not shrink the
full frame or mix in either other candidate. These preexisting prototypes need
no source-body patch; their exact compile-option changes are in build JSON.

Generic/reference/integer paths retain their original implementation; baseline
fallback is a separate executable. Stage 1's head header is byte-identical.

The existing deferred strategy 3 is outside scope. Each trial starts from Stage
1 source, is independently tested and is never combined with another trial.

Assembly: baseline updater has 529 static instructions /
632 stack bytes; primary candidate has
583 /
664. Sorting removes three generic sorting
call sites; row fusion instead grows the updater to 1,068 static instructions
and 1,016 stack bytes, versus 529/632 in the baseline.
These are pre-link compiler assembly counts for `nnue.cpp`, not disassembly
of the final linked EXE. Both head dispatch bodies have 669 static instructions and identical instruction
counts. Neither inspected updater/head body has FMA instructions. Larger inline
code and stack are recorded tradeoffs, not assumed improvements. Full assembly
and extracted updater/head listings are preserved; static counts are not dynamic
execution counts or cycle measurements.

## Correctness

* Existing native oracle: **31,876 move transitions and
  26,908 null transitions**, bitwise lanes/head/CP parity against
  the original ordered generic updater; parent and sibling restoration passes.
* Independent seeded targeted walk: **8,264 recorded edges**
  across quiet, capture, king, castling, promotion, legal/pinned EP, rights and
  null cases; deep continuations, roots, poisoned child lanes and sibling
  restoration. Candidate and Stage 1 whole-walk float/head digests match:
  `6930010358689641942`. All relevant 128 float lanes are compared.
* Head regression: **161,420 bitwise comparisons**,
  256 existing golden FENs, arbitrary finite frames and both turns; four NaN-head
  cases, 1,920 special clipping lanes, infinities,
  signed zero, CP rounding and mate clamp boundaries. Original 32/16 golden
  expected CP values are not incorrectly applied to this 64/32 model.
* Exact search: all 12 fixtures at depth 5, 200k and 1M nodes; best move, score,
  PV, nodes, depth, seldepth and every reported counter match Stage 1. Every
  repeated fixed-node pair in the primary performance schedule also matches.
* Explicit UCI interruption: 24 cancellation checks, legal final moves and
  unchanged caller boards; all 12 following 200k-node reruns match. Terminal
  draws/checkmate/stalemate, disabled-SIMD scalar fallback and 12 classical
  200k-node comparisons pass. Production/UI code was untouched; no desktop
  launch or claim of a new full GUI regression run is made.
* A separate correctness-only sort observer asserts the **internal board/history
  and root accumulator bits** are restored after search returns, including stop
  and node-limit interruption. Its cancellation, rerun, classical and terminal
  regressions pass. This observer was not used for performance measurements.
* Existing legacy compatibility suite: **147 passed, 13 deselected**. It uses
  the preserved 32/16 compatibility binary for original golden scores, feature
  contract, incremental/rebuild agreement and terminal precedence. This does
  not substitute old-model expected scores for the new 64/32 parity tests.

Bitwise claims concern incremental accumulators relative to the original ordered
updater. A fresh full feature rebuild adds rows in a different order and is not
misrepresented as bitwise equivalent to incremental summation.

## Actual updater microbenchmarks

Seven rotated baseline/candidate process pairs, 100,000 iterations/category,
1,000 warmups/component, seeded varied edges, consumed outputs/compiler barriers.
The update column includes legal state extraction plus copying, sorting and rows;
the total path also constructs the move delta (boards are already made).

| Move class | Edges | Stage 1 update ns | Candidate update ns | Paired update speedup | Total path ns, baseline / candidate |
|---|---:|---:|---:|---:|---:|
| capture | 239 | 56.34 | 55.34 | 1.027x | 64.89 / 61.00 |
| castling | 18 | 101.75 | 100.10 | 0.991x | 106.64 / 105.20 |
| ep | 8 | 97.36 | 99.40 | 0.981x | 101.44 / 104.01 |
| high_features | 472 | 58.64 | 53.59 | 1.095x | 62.39 / 61.26 |
| king | 1,700 | 57.07 | 54.26 | 1.052x | 73.33 / 67.14 |
| mixed | 8,264 | 79.28 | 66.61 | 1.255x | 86.85 / 72.32 |
| null | 3,640 | 51.57 | 42.80 | 1.265x | 55.23 / 44.18 |
| promotion | 98 | 41.29 | 35.39 | 1.167x | 48.54 / 39.52 |
| quiet | 2,393 | 64.47 | 59.75 | 1.074x | 83.48 / 76.52 |
| rights | 168 | 88.76 | 88.67 | 1.012x | 91.40 / 93.13 |

Mixed-case update median: **79.28 →
66.61 ns**, paired factor
**1.255x**. The mixed micro corpus is
null-heavy (~44%) versus ~0.3% in search; this average is not a production-weighted
gain. Per-move categories and whole search are the authority for applicability.

Final micro measurements use explicit per-iteration object memory operands to
prevent compiler dead-store removal, plus an identical 1,872-byte Edge layout
with a fixed 152-byte state slot for all builds. This avoids crediting strategy
5 for shrinking the stored test corpus. The active returned state remains 24
bytes in that variant. Initial/checksum-only and intermediate pre-padding
micro results are retained as superseded exploratory records, never pooled with
final measurements. These bounded measurement corrections rebuilt only harnesses
and did not repeat or alter any full-search engine/results.

Mixed prepared updater (states already extracted):
73.21 /
64.19 ns; divided by its
2.470 average changed rows across both perspectives,
29.64 /
25.99 ns/row. That quotient includes
copying/bookkeeping and is **not isolated row-arithmetic latency**. Synthetic
copy-only references are 34.61 /
32.97 ns; metadata-only references
3.40 /
3.40 ns. Components have separate
loop/cache contexts; do not subtract/add them to reconstruct production costs.
Full per-category component results and paired IQRs are in `analysis-sort.json`.

## Whole-search results against Stage 1 clip

Primary statistic: `exp(mean(median(log(paired wall-NPS ratio))))` across
positions, giving each fixture equal weight. Medians are taken in log space;
the display table uses conventional arithmetic middle-pair medians, a negligible
difference for the ten-pass trial here. For fixed nodes this is the paired
inverse wall-time ratio. Hierarchical 95% bootstrap: resample positions, then
paired repetitions inside positions, 10,000 draws, seed 20261017. Repeats are not
independent chess positions. These intervals describe this fixture suite, not
universal workloads, exact CPU cycles or Elo.
The bootstrap does not remove systematic background-load, frequency or order
effects, or explicitly model temporal autocorrelation between measurements.

| Control | Paired factor (gain) | Grouped 95% interval | Position median range |
|---|---:|---:|---:|
| 200,000 nodes | 1.0275x (+2.75%) | 1.0082–1.0387x | 1.0035–1.0535x |
| 1,000,000 nodes | 1.0275x (+2.75%) | 1.0066–1.0456x | 0.9698–1.0674x |
| 100 ms | 1.0322x (+3.22%) | 1.0103–1.0563x | 1.0010–1.0882x |
| 500 ms | 1.0282x (+2.82%) | 1.0011–1.0509x | 0.9905–1.0746x |
| 1,000 ms | 1.0278x (+2.78%) | 1.0079–1.0408x | 0.9844–1.0532x |

### Per-position median paired speedups

| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1000 ms |
|---|---:|---:|---:|---:|---:|
| opening | 1.0306x | 1.0302x | 1.0118x | 0.9905x | 1.0203x |
| quiet_middlegame | 1.0202x | 1.0674x | 1.0159x | 1.0063x | 1.0395x |
| tactical | 1.0035x | 1.0098x | 1.0189x | 1.0276x | 0.9846x |
| pawn_endgame | 1.0535x | 1.0396x | 1.0882x | 1.0339x | 1.0419x |
| piece_endgame | 1.0374x | 1.0437x | 1.0762x | 1.0747x | 1.0322x |
| imbalance | 1.0172x | 1.0239x | 1.0011x | 1.0099x | 1.0453x |
| castling_rights | 1.0331x | 1.0151x | 1.0302x | 1.0403x | 1.0269x |
| promotion | 1.0279x | 0.9698x | 1.0238x | 1.0271x | 1.0532x |
| en_passant | 1.0155x | 1.0535x | 1.0502x | 1.0108x | 1.0232x |
| pins | 1.0296x | 1.0532x | 1.0324x | 1.0646x | 1.0231x |
| attack_complex | 1.0247x | 1.0038x | 1.0262x | 0.9979x | 1.0139x |
| opening_history | 1.0376x | 1.0251x | 1.0153x | 1.0596x | 1.0310x |

4 / 60 fixture/control medians were below 1.0; material (>3% elapsed)
regressions: **1**. These are medians, not guarantees
that every individual noisy pair wins. `per-position-sort.csv` also reports
wall NPS/time, actual nodes, depth, seldepth, evaluations and qnodes for both builds;
JSON includes repeat CV, paired quartiles and order-specific estimates. Timed
search depth/decisions may differ because faster search reaches more nodes;
fixed-work decisions remain exact.

Below-unity medians: promotion 1,000,000 nodes: 0.9698x, opening 500 ms: 0.9905x, attack_complex 500 ms: 0.9979x, tactical 1,000 ms: 0.9846x.

### Per-position results: ordered parent-copy/row fusion

| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1000 ms |
|---|---:|---:|---:|---:|---:|
| opening | 1.0082x | 0.9532x | 1.0099x | 1.0044x | 1.0031x |
| quiet_middlegame | 0.9957x | 0.9738x | 0.9847x | 0.9645x | 0.9721x |
| tactical | 0.9970x | 0.9831x | 1.0452x | 0.9672x | 1.0055x |
| pawn_endgame | 0.9657x | 1.0189x | 0.9968x | 0.9762x | 0.9633x |
| piece_endgame | 0.9956x | 0.9859x | 0.9871x | 0.9754x | 0.9871x |
| imbalance | 1.0085x | 0.9722x | 1.0020x | 0.9888x | 0.9767x |
| castling_rights | 0.9800x | 1.0266x | 0.9881x | 0.9961x | 0.9874x |
| promotion | 0.9885x | 0.9956x | 0.9768x | 0.9830x | 0.9639x |
| en_passant | 1.0000x | 0.9957x | 0.9565x | 0.9560x | 0.9692x |
| pins | 0.9994x | 1.0145x | 0.9611x | 0.9855x | 0.9484x |
| attack_complex | 0.9920x | 0.9494x | 0.9875x | 0.9913x | 0.9958x |
| opening_history | 0.9849x | 0.9722x | 0.9764x | 1.0032x | 0.9954x |

### Per-position results: small search-state temporary specialization

| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1000 ms |
|---|---:|---:|---:|---:|---:|
| opening | 0.9981x | 0.9813x | 0.9768x | 0.9990x | 1.0154x |
| quiet_middlegame | 1.0066x | 0.9871x | 0.9929x | 0.9803x | 0.9899x |
| tactical | 0.9779x | 0.9955x | 1.0053x | 0.9889x | 1.0050x |
| pawn_endgame | 0.9649x | 0.9834x | 0.9846x | 0.9830x | 0.9585x |
| piece_endgame | 0.9882x | 0.9849x | 0.9773x | 0.9669x | 0.9785x |
| imbalance | 0.9710x | 1.0065x | 0.9846x | 0.9794x | 0.9736x |
| castling_rights | 0.9842x | 0.9963x | 0.9776x | 1.0044x | 0.9788x |
| promotion | 0.9756x | 0.9760x | 0.9809x | 0.9908x | 0.9700x |
| en_passant | 0.9908x | 0.9680x | 0.9618x | 0.9978x | 0.9850x |
| pins | 0.9689x | 0.9924x | 0.9899x | 0.9695x | 0.9852x |
| attack_complex | 0.9781x | 0.9727x | 0.9634x | 0.9641x | 0.9877x |
| opening_history | 0.9550x | 0.9833x | 0.9914x | 0.9997x | 0.9871x |

## Fresh matched classical throughput context

Separate secondary measurement: three rotated classical/Stage 1/candidate
triples on the same 12 fixtures at 1000 ms (108 searches), identical controls.
This uses **fresh matched-position measurements**, not projections from older
scalar-head results. Geometric mean of per-fixture median paired NPS ratios to
classical: Stage 1 **0.8151**, candidate **0.8283**. The aggregate remaining
shortfall fraction recovered is **7.1%**, calculated as
`(candidate_ratio - stage1_ratio) / (1 - stage1_ratio)`.
This is descriptive with only three triples/fixture, and can be noisy; it is
not the average of individual shortfall recoveries. Different evaluators visit
different trees, so it is not equal-work evaluator cost or a strength estimate.
Raw triples, grouped intervals and load samples are in `classical-gap.json`.
The joint position/triple bootstrap gives a shortfall-recovery interval of
**-35.5% to
30.6%**,
conditional on a positive baseline shortfall; 11 of 10,000 draws had no positive
shortfall and were omitted/count recorded. Direct secondary candidate/Stage 1
speedup is 1.0055x, interval
0.9498–1.0601x.
**No reliable gap recovery is established, and this secondary comparison does
not overturn the inconclusive primary sort decision.** No historical projection
or Elo improvement is claimed.

## Final answers and stopping decision

1. **Largest maintenance bottleneck:** repeated bookkeeping is the largest
   recognizable envelope; tiny-list sorting and temporary-state handling are
   addressable parts, with their measured tradeoffs disclosed separately.
   Current observers cannot defensibly give an exact production suboperation ranking.
2. **Implemented:** independent tiny-sort, existing row-fusion and
   small-state trials; full Stage 1 updater remains available as the control.
3. **Updates:** mixed micro paired factor 1.255x,
   with the nonrepresentative null-heavy mix and per-class figures disclosed above.
4. **Whole engine:** the five Stage 1-relative factors and grouped intervals above
   are the primary result; none is measured against the original scalar head.
5. **Bitwise accumulators:** yes, all relevant float lanes and head/CP gates pass.
6. **Fixed decisions:** yes, all fixed-work scores, moves, PVs and counters match.
7. **Regressions:** 4 slightly negative fixture/control medians;
   1 material regression under the predeclared threshold.
8. **Classical gap:** distinguish the fresh secondary comparison above from any
   historical extrapolation; no Elo recovery or engine promotion is implied.
9. **Next:** investigate the promotion regression's generated code and try a
   smaller sorting fast path in a separately approved follow-up. That addresses
   the strongest positive signal without assuming the broader sort is safe.
   The unchanged head remains a large named cost. Full-frame specialization or
   deferred updates need a separate design/parity study. No such work began.

The bounded trials are complete; use the acceptance status above rather than
combining independently unverified changes. Shrinking the actual frame, unlike
the small-state temporary, requires a larger ownership/API redesign and is
deferred. Trials and their statuses are listed above. There were no combinations,
games, more than three candidates, or repetitions beyond the ten-pass ceiling.
The three-candidate budget is exhausted. Rejected implementations remain archived
as research evidence, not selected optimizations. Stage 1 remains the winner;
the active engine and classical default are unchanged. No further tests or
Stage 3 work are scheduled.

## Preservation and artifacts

**800/800 protected files unchanged**,
including production code/executables, selected checkpoint/export, previous
models and studies, and Stage 1 sources/binaries. Sealed data was not enumerated
or read. Baseline/candidate source copies, generated headers, EXE/PDB and full
assembly are local under this workspace's ignored `artifacts/` directory on Z:.
Committed scripts, focused patches, raw measurements, parity receipts and
normalized text/artifact manifests support reproduction. See workspace README
for exact commands and prerequisite local artifacts. The report is mirrored in
the workspace and compared after LF normalization.
