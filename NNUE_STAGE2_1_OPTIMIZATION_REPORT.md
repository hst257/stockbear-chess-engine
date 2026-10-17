# StockBear — Stage 2.1 targeted tiny-list sorting report

## Executive decision

**Refined candidate: INCONCLUSIVE.**
Retain accepted Stage 1 as the experimental baseline; no refined candidate met every acceptance gate.
One new candidate was implemented: lengths 0–2 use an explicit no-op or one
strict compare/swap; larger state/changed-row lists retain `std::sort`.
The prior full insertion-sort comparator remains separately selectable and is
**INCONCLUSIVE** in this fresh study. No rejected Stage 2 fusion/state changes
were combined. The active StockBear executable and classical default are unchanged.

The original promotion slowdown did **not reproduce reliably** in the small
pre-implementation diagnostic. That result alone neither accepts the old sort
nor establishes its original slowdown's cause. This report separates diagnosis,
counter-only observation, microbenchmarks, and the predeclared full search.

## Frozen baseline, isolation and limits

Branch: `codex/nnue-stage2-1-tiny-sort`, primary parent Stage 1
`f397a5af002900bbc15a7261dc6027c48daaeff4`. Prior Stage 2 evidence is preserved at
`004281cb8a24357e61229c8945d8d4aababc4a4c` and copied reference hashes are archived locally.
There were no routine intermediate commits in this follow-up.
`baseline_commit` identifies the measured baseline; the inherited historical
`source_revision` field in the frozen plan refers to the earlier Stage 1 setup.

* Accepted baseline: exact Stage 1 `NNUEKernel=clip`, compact strategy 2;
  SHA-256 `e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d`.
* Imported Stage 2 full insertion-sort binary:
  `9993433e680823c439dbb0b6234244ffab29792af2aeb2eeda9af1ce358d599d`.
* Refined binary:
  `1adf9b63f848737bf8958a9ebb4ae736edd50f9b3a5156d3752188a6726f1ff4`.
* Model remains 780 → dual 64 → 32 → 1, 54,209 parameters. Export SHA-256
  `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`; checkpoint SHA-256
  `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`.
* Identical Zig 0.13/Clang 18, C++17, `-O2 -pthread -Wall -Wextra
  -ffp-contract=off`; no added fast-math, reassociation, FMA contraction or LTO.
* One search thread, CPU0 affinity, 16 MiB hash, fresh TT per go, no pondering,
  identical FENs/full histories, identical search options and `clip`.
* 7 rotated three-way passes × 16 positions × five controls =
  **1,680 primary searches**. Search schedule wall runtime:
  17.1 minutes; predeclared cap 45 minutes, maximum ten
  passes. Diagnostic and observer schedules are separate and not pooled.

The study stops at seven passes. The original promotion loss did not persist,
but the refinement has other material fixture medians and incomplete interval/
order support. These records support a conservative inconclusive decision;
extra result-driven passes or another threshold fit were not needed for this
bounded follow-up. No search was replayed or silently added.

The 12-position suite is unchanged. Four additional hand-selected legal
promotion positions were frozen in `supplementary-positions.json` before candidate
selection. Three other positions plus the original promotion fixture were used
only for the initial diagnostic. Supplementary performance did not guide tuning;
no second candidate was fitted after those results. These are small engineering
fixtures, not a strength sample or training dataset.

AC was online at the recorded before/after checks. The OEM Acer plan and last
user-confirmed Quiet/Eco setting were retained; no settings or unrelated apps were changed.
NitroSense's current mode and temperature/throttling are not independently
observable here. CPU-intensive work ran serially. Primary background load after
subtracting benchmark processes: median
12.73%, range
9.43–27.13%
of total logical capacity. This is not CPU0 contention or boost/thermal telemetry.

## Promotion regression diagnosis

| Study | Fixture | Full sort / Stage 1 | Repeat-only 95% | Baseline first | Sort first | Load correlation |
|---|---|---|---|---|---|---|
| original | promotion | 0.9698× | [0.9086, 1.0219] | 0.9692× | 0.9845× | -0.593 |
| diagnostic | promotion | 1.0487× | [0.9710, 1.1891] | 1.0273× | 1.1264× | -0.562 |
| diagnostic | diagnostic_promotion_1 | 1.0744× | [1.0093, 1.1392] | 1.1073× | 1.0406× | -0.495 |
| diagnostic | diagnostic_promotion_2 | 1.0641× | [1.0066, 1.1339] | 1.0201× | 1.1218× | 0.044 |
| diagnostic | diagnostic_promotion_3 | 1.0466× | [1.0122, 1.0760] | 1.0473× | 1.0466× | -0.670 |

The original 10-pair promotion result has a repeat-bootstrap interval crossing
one. The fresh five-pair diagnostic has positive medians at all four positions,
but the original fixture's interval also crosses one. Order subsets differ;
aggregate background CPU is only an observational segment measurement. These
small samples do not prove a load, scheduling, cache or sorting cause.

Promotion substitutes a pawn feature with the promoted-piece feature; a capture
adds another removal, and rights/EP transitions can add state rows. Both
perspectives sort their own signed feature indices before float row operations.
Ordinary promotions thus exercise 2-row or 3-row cases; state transitions can
make lists larger. This v2 model is not king-relative, so no promotion refresh
or king-bucket switch is involved. Original row order and signs are preserved.
Generated code growth and inlining are examined below; no hardware cache-miss,
branch-miss or cycle counters establish an instruction-cache explanation.

## Actual sorting workload

45 observer searches (15 positions × three passes), **9,000,000 fixed nodes**.
The extra 50k-node warmup record is excluded. Both lists are sorted once per
perspective/update, so each type has the same call count. The observer counts
actual reference comparisons, sortedness, equal keys and key bins. A separate
shadow insertion model counts comparisons/shifts; these are algorithmic counts,
not retired machine instructions. There are no per-operation clocks.

| List | Length | Calls | Share |
|---|---|---|---|
| state | 0 | 14,497,860 | 80.617% |
| state | 1 | 822,582 | 4.574% |
| state | 2 | 767,622 | 4.268% |
| state | 3 | 415,542 | 2.311% |
| state | 4 | 1,465,680 | 8.150% |
| state | 5 | 14,322 | 0.080% |
| rows | 0 | 45,288 | 0.252% |
| rows | 1 | 252 | 0.001% |
| rows | 2 | 13,244,322 | 73.647% |
| rows | 3 | 4,388,556 | 24.403% |
| rows | 4 | 206,316 | 1.147% |
| rows | 5 | 80,346 | 0.447% |
| rows | 6 | 18,384 | 0.102% |
| rows | 7 | 144 | 0.001% |

| List | Calls | Already sorted | Reverse sorted | Equal-key calls | Reference comparisons | Shadow insertion comparisons | Shadow shifts |
|---|---|---|---|---|---|---|---|
| state | 17,983,608 | 94.46% | 85.46% | 0 | 8,479,206 | 8,479,197 | 3,422,535 |
| rows | 17,983,608 | 39.31% | 36.09% | 0 | 27,727,878 | 27,197,553 | 13,222,467 |

Sorted/reverse categories overlap for length 0/1 or equal lists. No equal keys
were observed. Legal orthodox piece removals/additions use distinct piece-square
features; captured pieces have a different color feature, and intersecting old/new
state features cancel before row creation. Piece and state feature ranges are
disjoint. No general duplicate-free API assumption is imposed by the new helper:
synthetic equal-key identity is also checked against the reference.

| Originating search routine | Calls per list type |
|---|---|
| ordinary_parent | 13,914,882 |
| quiescence_parent | 4,068,726 |

| Transition class | Calls per list type |
|---|---|
| capture | 3,377,652 |
| castling | 43,812 |
| en_passant | 5,748 |
| king | 4,787,370 |
| null | 45,540 |
| promotion | 86,568 |
| quiet | 9,440,658 |
| rights_changing_quiet | 196,260 |

Phase labels describe the parent routine issuing the update, not the child's
eventual visit type. Key histograms use 49-wide bins and are retained by
phase/move/type/length in `workload-raw.jsonl`; state indices are at 768–779,
signed row magnitudes span 1–780. Per-promotion/castling/EP distributions remain
available in the raw buckets.

Observer wall-time multiplier versus matched Stage 1: median
**1.366×**, range
1.046–1.871×.
Every observed fixed-work result matches. This overhead prevents treating
observer timing as uninstrumented production operation cost.

## Candidate and exact source changes

`selective_sort.hpp` returns for 0/1 entries, compares/swaps exactly once for two,
and uses the original strict comparator and `std::sort` for lengths 3–16.
State and signed-row wrappers are independent instantiations. A strict `<`
retains equal identities for two-element lists; larger equality behavior remains
with the reference implementation. No allocation or distribution-dependent
assumption is added. `selective.patch` changes only the two compact-updater sort
call sites and adds the helper include in the private `nnue.cpp` copy.

The threshold is selected from the 73.6% two-row / 24.4% three-row distribution
and empty-state prevalence. It prioritizes a minimal common path over another
large inlined insertion loop. It is not claimed to be a universal optimum; no
threshold sweep or supplementary-set tuning took place. Original Stage 1 and
full Stage 2 sort remain distinct source trees and executables.

## Correctness and restoration

| Implementation | Sorting cases | Equal-key identity mismatches | Legal/null transitions | Head bit checks | Fixed-work comparisons |
|---|---|---|---|---|---|
| sort | 272,000 | 0 | 31,876 / 26,908 | 161,420 | 48 |
| selective | 272,000 | 0 | 31,876 / 26,908 | 161,420 | 48 |

Sorting cases cover lengths 0–16, random/permuted/sorted/reverse inputs,
duplicates, opposite signed rows with equal absolute keys, and feature boundaries;
state tests use uint16 keys. Legacy full insertion sorting is retained only as
its original legal unique-key comparison. Any synthetic tie behavior is explicitly
counted, never silently substituted for the new candidate's strict reference gate.

Each accumulator corpus has 8,264 deterministic edges across quiet/capture,
promotion, castling, EP, king, rights and null transitions, deep walks, poisoned
child frames, sibling isolation and root initialization. All 128 relevant float
lanes and head/CP checks match the reference. Whole-walk digest:
`6930010358689641942`. The original 31,876 legal / 26,908 null oracle passes.
Head tests retain 256 golden FENs, 161,420 bit comparisons, clipping boundaries,
signed zeros, extreme finite values, 1,920 special lanes, four NaN cases and
CP rounding/mate clamp checks. No floating reassociation is permitted.

Depth 5, 200k and 1M searches on all 16 fixtures match moves, scores, PVs, nodes,
completed depth, seldepth, evaluations, qnodes and all reported counters. Every
repeated fixed-node primary block also matches. Each variant passes 24 explicit
UCI cancellation checks, 12 following fixed-node reruns, terminal/draw precedence,
disabled-SIMD fallback and 12 unchanged classical searches. A separate correctness-
only refined observer asserts internal board/history and root accumulator bits
after return, including interrupted searches; those regressions pass. It is never
used for timing. Production/UI was untouched; no new GUI/full pytest run is claimed.

## Actual update-path microbenchmarks

Seven rotated triples, 100,000 iterations/category, 1,000 warmups. A deterministic
varied legal corpus and identical 1,872-byte edge / 152-byte state-slot footprint
are used by every build. Explicit per-iteration memory operands prevent dead-store
elimination. All corpus/head digests match. Frame layout remains 1,176 bytes.
Latency medians and paired factors are separate summaries; division of displayed
medians need not equal a median paired factor. Raw records retain variation.

| Class | Stage 1 ns | Full sort ns | Refined ns [IQR] | Full / Stage 1 | Refined / Stage 1 | Delta+update ns, base / refined |
|---|---|---|---|---|---|---|
| capture | 63.58 | 56.04 | 57.07 [56.47, 60.83] | 1.1691× | 1.0813× | 69.96 / 63.56 |
| castling | 112.05 | 105.45 | 110.38 [105.32, 126.92] | 1.0406× | 1.0084× | 119.13 / 112.80 |
| ep | 106.03 | 101.93 | 108.72 [104.27, 111.43] | 1.0219× | 0.9752× | 109.44 / 107.04 |
| high_features | 62.35 | 56.37 | 54.90 [53.13, 57.73] | 1.1152× | 1.1494× | 66.78 / 58.32 |
| king | 60.72 | 54.80 | 52.58 [49.85, 53.22] | 1.1198× | 1.2195× | 77.48 / 73.28 |
| mixed | 91.76 | 72.05 | 72.22 [66.43, 72.37] | 1.2968× | 1.2981× | 92.81 / 82.34 |
| null | 56.82 | 41.06 | 41.76 [40.51, 49.45] | 1.3736× | 1.3295× | 59.67 / 47.35 |
| promotion | 41.24 | 35.48 | 36.02 [34.61, 38.47] | 1.1943× | 1.1639× | 49.66 / 40.58 |
| quiet | 68.95 | 62.87 | 62.47 [57.96, 66.97] | 1.0697× | 1.1016× | 92.32 / 79.89 |
| rights | 97.00 | 90.04 | 97.60 [93.82, 99.02] | 1.0508× | 0.9462× | 99.39 / 98.74 |

Update includes state extraction, lane copying, metadata and ordered rows;
delta+update additionally constructs the actual move delta. Boards are already
made. The mixed corpus is ~44% null edges, whereas observed searches are ~0.25%
null transitions. Its aggregate is not a production-weighted speedup. King, EP,
promotion and other categories must be assessed individually and with full search.

### Sorting latency by length

These isolated tables use 256 varied integer lists per length, restored into
the same 64-byte scratch before each sort, plus a separately saved copy-only
reference. They therefore measure **copy + sorting**, not subtraction-derived
pure sorting cycles. State-key inputs here use integer scratch; actual uint16
state execution is covered by the full update measurement and ordering tests.
All lists, including lengths beyond legal state-list size five, are identical
across implementations. Non-production lengths are diagnostic only.

#### Signed rows

| Length | Stage 1 ns | Full sort ns | Refined ns | Refined paired factor |
|---|---|---|---|---|
| 0 | 2.75 | 0.65 | 0.87 | 3.2936× |
| 1 | 2.63 | 0.65 | 0.87 | 3.7636× |
| 2 | 4.95 | 1.42 | 1.11 | 4.4728× |
| 3 | 3.66 | 4.12 | 3.63 | 0.9951× |
| 4 | 5.93 | 5.52 | 5.95 | 0.9819× |
| 5 | 7.52 | 8.09 | 7.51 | 0.9992× |
| 6 | 10.13 | 10.13 | 10.98 | 0.9911× |
| 7 | 12.43 | 12.38 | 13.59 | 0.9268× |
| 8 | 15.43 | 16.44 | 17.26 | 0.8768× |
| 9 | 18.93 | 17.76 | 19.07 | 0.9607× |
| 10 | 21.80 | 22.44 | 23.32 | 0.9372× |
| 11 | 25.81 | 28.11 | 27.42 | 0.9684× |
| 12 | 28.85 | 33.74 | 31.07 | 0.9453× |
| 13 | 36.73 | 34.50 | 37.65 | 1.0040× |
| 14 | 43.36 | 50.71 | 46.51 | 0.9118× |
| 15 | 52.57 | 59.24 | 48.12 | 1.0051× |
| 16 | 61.63 | 89.84 | 60.52 | 0.9857× |

#### State-key integers

| Length | Stage 1 ns | Full sort ns | Refined ns | Refined paired factor |
|---|---|---|---|---|
| 0 | 2.76 | 0.65 | 0.87 | 3.4489× |
| 1 | 2.52 | 0.65 | 0.87 | 3.3142× |
| 2 | 4.86 | 1.57 | 1.36 | 3.4797× |
| 3 | 3.62 | 3.40 | 3.62 | 1.0050× |
| 4 | 5.84 | 5.50 | 6.66 | 0.8471× |
| 5 | 7.62 | 7.70 | 7.68 | 0.9918× |
| 6 | 9.23 | 9.47 | 10.46 | 0.9246× |
| 7 | 13.77 | 12.57 | 13.87 | 0.9759× |
| 8 | 14.98 | 14.89 | 15.14 | 1.0407× |
| 9 | 16.86 | 18.05 | 18.25 | 0.9235× |
| 10 | 22.22 | 21.22 | 20.96 | 1.0274× |
| 11 | 24.25 | 25.98 | 27.31 | 0.8677× |
| 12 | 29.91 | 31.85 | 32.15 | 0.9920× |
| 13 | 36.42 | 39.60 | 39.20 | 0.9216× |
| 14 | 39.11 | 55.77 | 40.08 | 0.9569× |
| 15 | 45.95 | 61.82 | 46.73 | 0.9376× |
| 16 | 54.40 | 87.16 | 59.84 | 0.8978× |

## Whole-engine throughput and uncertainty

Statistic: geometric mean of per-position median log paired wall-NPS ratios.
For fixed nodes, this is the inverse paired wall-time ratio. Hierarchical 95%
bootstrap: 10,000 draws, positions resampled as groups and repeats resampled
inside each position, seed 20261017. Seven repeats are not seven independent
positions. Frozen and supplementary suites remain separate; no pooled headline
uses the extra promotion cases to improve the frozen-suite result.
Intervals describe these fixtures and conditions, not Elo. They do not model
temporal autocorrelation, remove background/frequency variation, or establish a
multiple-comparison-adjusted family. Rotated and reversed blocks provide order
sensitivity checks. Full JSON preserves all moves/PVs/counters and iterations.

### Frozen 12

| Control | Full sort / Stage 1 [95%] | Refined / Stage 1 [95%] | Refined order subset medians |
|---|---|---|---|
| 200,000 nodes | 1.0127× [0.9963, 1.0364] | 1.0085× [0.9894, 1.0284] | 1.0116× / 1.0108× |
| 1,000,000 nodes | 1.0159× [1.0007, 1.0412] | 1.0115× [0.9942, 1.0334] | 0.9972× / 1.0211× |
| 100 ms | 1.0107× [0.9779, 1.0438] | 1.0219× [0.9899, 1.0501] | 1.0256× / 1.0128× |
| 500 ms | 1.0287× [1.0108, 1.0487] | 1.0321× [1.0071, 1.0542] | 1.0234× / 1.0413× |
| 1,000 ms | 1.0253× [1.0036, 1.0540] | 1.0286× [1.0043, 1.0513] | 1.0273× / 1.0069× |

### Supplementary promotion 4 (exploratory)

| Control | Full sort / Stage 1 [95%] | Refined / Stage 1 [95%] | Refined order subset medians |
|---|---|---|---|
| 200,000 nodes | 1.0362× [0.9954, 1.0650] | 1.0241× [0.9935, 1.0661] | 1.0293× / 1.0459× |
| 1,000,000 nodes | 1.0375× [0.9895, 1.0688] | 1.0293× [1.0114, 1.0562] | 1.0289× / 1.0489× |
| 100 ms | 1.0371× [0.9864, 1.0931] | 1.0190× [0.9839, 1.0620] | 1.0187× / 1.0190× |
| 500 ms | 1.0243× [0.9989, 1.0682] | 1.0342× [0.9977, 1.0811] | 1.0031× / 1.0568× |
| 1,000 ms | 1.0250× [0.9940, 1.0721] | 1.0162× [1.0006, 1.0648] | 1.0159× / 1.0208× |

### Direct refined versus full insertion sort, frozen suite

| Control | Paired factor | Grouped 95% |
|---|---|---|
| 200,000 nodes | 0.9894× | [0.9703, 1.0130] |
| 1,000,000 nodes | 0.9906× | [0.9711, 1.0145] |
| 100 ms | 0.9983× | [0.9730, 1.0304] |
| 500 ms | 1.0007× | [0.9793, 1.0199] |
| 1,000 ms | 0.9935× | [0.9707, 1.0183] |

### Baseline drift sensitivity

| Control | Lowest / highest normalized baseline pass |
|---|---|
| 200,000 nodes | 0.9504× / 1.0490× |
| 1,000,000 nodes | 0.9686× / 1.0400× |
| 100 ms | 0.9613× / 1.0000× |
| 500 ms | 0.9725× / 1.0522× |
| 1,000 ms | 0.9724× / 1.0442× |

Each baseline pass is normalized to each fixture's across-pass median NPS, then geometrically averaged across the frozen suite. Drift is an environmental sensitivity signal, not measured throttling or a correction applied to results.

### Per-position factors: selective

| Fixture | 200k | 1M | 100 ms | 500 ms | 1000 ms |
|---|---|---|---|---|---|
| opening | 0.9960× | 0.9857× | 1.0048× | 0.9811× | 1.0198× |
| quiet_middlegame | 1.0110× | 1.0373× | 1.0385× | 1.0682× | 1.0053× |
| tactical | 1.0099× | 1.0059× | 0.9784× | 1.0349× | 1.0074× |
| pawn_endgame | 1.0328× | 0.9992× | 1.0579× | 1.0114× | 1.0069× |
| piece_endgame | 1.0191× | 1.0398× | 0.9620× | 1.0642× | 1.0534× |
| imbalance | 1.0122× | 1.0109× | 1.0485× | 1.0521× | 1.0455× |
| castling_rights | 0.9877× | 0.9811× | 1.0034× | 1.0148× | 1.0122× |
| promotion | 1.0334× | 1.0137× | 1.0228× | 1.0236× | 1.0385× |
| en_passant | 1.0168× | 1.0331× | 1.0826× | 1.0062× | 1.0828× |
| pins | 0.9661× | 0.9903× | 0.9845× | 1.0471× | 1.0135× |
| attack_complex | 1.0080× | 1.0291× | 1.0640× | 1.0527× | 1.0204× |
| opening_history | 1.0105× | 1.0143× | 1.0226× | 1.0325× | 1.0399× |
| validation_promotion_1 | 1.0178× | 1.0170× | 1.0060× | 1.0681× | 1.0188× |
| validation_promotion_2 | 1.0581× | 1.0409× | 1.0392× | 1.0451× | 1.0056× |
| validation_promotion_3 | 1.0391× | 1.0301× | 1.0095× | 1.0035× | 1.0228× |
| validation_promotion_4 | 0.9828× | 1.0293× | 1.0217× | 1.0214× | 1.0176× |

Material fixture/control medians (>3% elapsed): **2**.

| Fixture | Control | Factor |
|---|---|---|
| pins | 200,000 nodes | 0.9661× |
| piece_endgame | 100 ms | 0.9620× |

### Per-position factors: sort

| Fixture | 200k | 1M | 100 ms | 500 ms | 1000 ms |
|---|---|---|---|---|---|
| opening | 1.0220× | 1.0033× | 0.9179× | 1.0150× | 0.9859× |
| quiet_middlegame | 1.0094× | 1.0251× | 1.0499× | 1.0421× | 1.0355× |
| tactical | 1.0130× | 0.9861× | 0.9937× | 1.0301× | 1.0064× |
| pawn_endgame | 1.0164× | 1.0631× | 1.0316× | 1.0670× | 1.0079× |
| piece_endgame | 1.0200× | 1.0053× | 0.9953× | 1.0315× | 1.0480× |
| imbalance | 0.9859× | 1.0004× | 0.9328× | 1.0072× | 1.0281× |
| castling_rights | 1.0052× | 1.0273× | 1.0307× | 1.0348× | 1.0303× |
| promotion | 1.0555× | 1.0666× | 1.0191× | 1.0289× | 1.0365× |
| en_passant | 0.9543× | 1.0299× | 1.0638× | 1.0046× | 1.0505× |
| pins | 1.0146× | 0.9926× | 0.9952× | 1.0669× | 1.0276× |
| attack_complex | 1.0101× | 1.0128× | 1.0598× | 0.9913× | 1.0210× |
| opening_history | 1.0501× | 0.9824× | 1.0506× | 1.0275× | 1.0280× |
| validation_promotion_1 | 1.0218× | 1.0079× | 1.0297× | 1.0364× | 1.0335× |
| validation_promotion_2 | 1.0367× | 1.0551× | 1.0757× | 1.0309× | 1.0198× |
| validation_promotion_3 | 1.0525× | 1.0309× | 1.0302× | 1.0105× | 1.0207× |
| validation_promotion_4 | 1.0341× | 1.0569× | 1.0140× | 1.0198× | 1.0261× |

Material fixture/control medians (>3% elapsed): **3**.

| Fixture | Control | Factor |
|---|---|---|
| en_passant | 200,000 nodes | 0.9543× |
| opening | 100 ms | 0.9179× |
| imbalance | 100 ms | 0.9328× |

`per-position-*.csv` additionally reports wall NPS/time, nodes, depth, seldepth,
evaluation calls and qnodes. JSON includes paired IQRs, repeat CV and order
subsets. Timed searches can reach different nodes/depths while all fixed-work
decisions remain identical. No inference about playing strength is made.

## Generated assembly

| Updater | Static instructions | Stack bytes | Static jump instructions | Sort call sites | FMA |
|---|---|---|---|---|---|
| baseline | 529 | [632] | 52 | 3 | 0 |
| sort | 583 | [664] | 70 | 0 | 0 |
| selective | 576 | [648] | 64 | 3 | 0 |

| Linked executable | Updater symbol bytes | Head symbol bytes |
|---|---|---|
| baseline | unavailable | 3527 |
| selective | unavailable | 3527 |
| sort | unavailable | 3527 |

Listings come from `nnue.cpp -S` with recorded strict flags, before final
linking; these are not final-EXE disassembly, dynamic branch counts or cache
pressure measurements. The additional function-byte table is measured from local
final-EXE PDB symbols; it is not a cache-miss measurement. Helper inlining and remaining `std::sort` calls can be
inspected in the preserved excerpts/full assembly. Head instruction counts and
Stage 1 header bytes remain identical. Changed static size/stack are potential
tradeoffs, not proof of a microarchitectural cause for a fixture slowdown.

The tiny helper's common-case work is inlined into the emitted states updater;
there are no separate tiny-helper calls in that body. The refined fallback still
has three generic-sort call sites. The emitted search wrapper is identical in
size/counts across builds (32 instructions, 184 stack bytes) and calls the states
updater. Direct/local-PDB lookup and enumeration did not resolve either updater
symbol, so final linked updater byte sizes are unavailable. This is not evidence
that the whole updater was inlined or that cache pressure caused a regression.

## Acceptance and final answers

| Candidate | Decision | All frozen intervals positive | Long promotion controls | Both long-control orders | Material medians |
|---|---|---|---|---|---|
| sort | INCONCLUSIVE | no | not established | positive | 3 |
| selective | INCONCLUSIVE | no | positive | not established | 2 |

Acceptance requires all exact gates, positive frozen-suite control intervals,
corroboration at long controls on the separate promotion validation set and both
order subsets, and no unexplained material regression. Approximately 3% is a
practical target; no arbitrary minimum 3% gain cutoff is imposed. Fragile aggregate
positivity or micro-only gains cannot establish acceptance.

1. **Original regression reproduced?** Not reliably in the five-pair diagnostic;
   the independent primary promotion results and full per-position table above
   provide the later validation evidence.
2. **Cause?** Unproven. Sort code size/inlining, scheduling/frequency/background
   load and ordinary sampling variation remain possible. No hardware counters
   establish a cache/branch explanation.
3. **Dominant sizes?** Two changed rows (73.6%), then three (24.4%); state lists
   are empty in 80.6% of observed calls. There are no observed equal keys.
4. **Best approach?** Keep Stage 1 as the accepted choice. Refined status is
   **INCONCLUSIVE** and prior full-sort status is **INCONCLUSIVE**. The refinement
   does not establish a robust whole-search advantage over the full sort;
   microbenchmark winners vary by transition class.
5. **Accumulator speed?** Refined paired update factors are 1.102× quiet,
   1.081× capture and 1.164× promotion. EP and rights updates
   regress in this micro corpus; all classes and total paths are tabulated.
   The null-heavy mixed average is not a search gain.
6. **Whole engine?** Refined one-million-node factor is
   1.0115× [0.9942, 1.0334];
   1000-ms factor is 1.0286×
   [1.0043, 1.0513]. The former crosses no gain, and
   aggregate timed gains do not remove the fixture/order failures.
7. **Regressions?** 2 refined and
   3 full-sort material fixture/control medians;
   all are enumerated rather than hidden by an aggregate.
8. **Exact correctness?** All required sorting, accumulator/head, fixed-work and
   interruption/restoration gates pass. No arithmetic order changed.
9. **Accept refined sort?** **INCONCLUSIVE.**
   Keep Stage 1 as the accepted fallback; do not promote the refinement.
10. **Next opportunity?** The unchanged float head remains the largest named
    cost in the verified Stage 1 sample (~32.37%; historical sampling, not a new
    post-refinement profile). A separately authorized dense-head/code-generation
    investigation has a larger measured target than additional tiny-sort tuning.
    No Stage 3, lazy updates, network changes or broader rewrite began here.

## Preservation, artifacts and reproduction

**813/813 protected files unchanged.**
The active executable, production source, model/checkpoint/export, previous
studies and original Stage 1/Stage 2 binaries are preserved. No sealed data was
enumerated/read; no training, labeling, tournaments or default changes occurred.
Stage 2 tracked evidence remains on its original branch/commit because this
branch starts from Stage 1; the archival references retain exact provenance.

The workspace README contains reproduction commands. Scripts, candidate headers,
focused patches, raw JSON/JSONL/CSV, test receipts and assembly excerpts are
committed. Complete source/binary/PDB/generated-header/assembly copies stay on Z:
under ignored `artifacts/`. Reproduction requires those preserved model/toolchain
inputs. `validation.json` and `manifest.json` record final integrity, uniqueness
and LF-normalized hashes. This report is mirrored in the workspace. The bounded
test is complete; no follow-up work or automated benchmarking is scheduled.
