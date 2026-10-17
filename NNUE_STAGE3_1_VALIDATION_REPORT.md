# StockBear — Stage 3.1 independent hidden-clipping validation

## Executive decision

**INCONCLUSIVE.** Retain Stage 1 as the accepted experimental baseline; the incomplete acceptance gates are identified below. The active engine, production source, weights, search policy and classical default are unchanged. No production promotion is authorized by this study.

Failed acceptance gates: `environmental_flags_within_budget`. **Every numerical, fixed-work, regression, order and dependence gate passes.** Formal acceptance is withheld solely because the frozen environmental limit was exceeded: 98/276 blocks (35.5%) were flagged, versus the predeclared 25% maximum. This is neither a demonstrated hiddenclip defect nor permission to relax the threshold after seeing favorable results.

Fresh general-suite factors: **1.0636×** at 1M nodes [1.0478, 1.0821] and **1.0741×** at 1000 ms [1.0573, 1.0918]. The separately repeated original 100-ms sentinel gives **1.0559×**, repeat-only 95% [1.0049, 1.0843]. Independent endgames at 100 ms give **1.0576×**, grouped 95% [1.0301, 1.0813].

The frozen schedule completed **3,072 searches / 1,536 pairs**, serially, in 26.6 minutes including warm-up, block probes and pauses. No tournaments, training, labeling, sealed-test access, rebuilds, new optimization variants or additional primary repetitions occurred. This validation is published in one final commit.

## Exact executable, model and build provenance

| Artifact | SHA-256 |
| --- | --- |
| StockBear_NNUE_training/scaling-experiment-20261016/artifacts/medium/best.pt | 7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264 |
| StockBear_NNUE_training/scaling-experiment-20261016/artifacts/native/medium/medium.sbnnue | a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3 |
| nnue-optimization-stage3-20261017/artifacts/baseline/engine.exe | e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d |
| nnue-optimization-stage3-20261017/artifacts/baseline/engine.pdb | 4de6a9d6002a4c6a66109a4a433e7e0c446111ae8e6bd02281ddd287f7630235 |
| nnue-optimization-stage3-20261017/artifacts/generated/nnue_dimensions.hpp | fd1cd6a1d8b711f2fbf140f436fc625a83882c75c24a6c3fdf428dfabdaec113 |
| nnue-optimization-stage3-20261017/artifacts/generated/nnue_weights.hpp | a538454ca8c7e0adeaff56d0b243b3863ee09994eb18f7d9dab1829be9cefabb |
| nnue-optimization-stage3-20261017/artifacts/hiddenclip/engine.exe | 68ced7162b20109b6ad9e705bbb4f43317c85d2cb5d10ff3ae45a02eb0bd571b |
| nnue-optimization-stage3-20261017/artifacts/hiddenclip/engine.pdb | 18fb8336e2b86471cf197332465e3295f52c59045c6489447fa908cd433b5c8d |

Both EXEs/PDBs match the original Stage 3 manifest. They resolve the same system CRT API-set/kernel imports; no local runtime replacement is involved. `build-provenance.json` preserves the original compiler commands, source hashes and current shared OS runtime hashes. Model weights are **embedded from identical frozen generated headers**, matching the archived export/checkpoint; these binaries do not dynamically load a newly supplied export.

Baseline provenance: Stage 1 `f397a5af002900bbc15a7261dc6027c48daaeff4`; validation branch starts from Stage 3 `3aaaf5046993c154793845a4e865d9fd51832dec`. Zig 0.13 / Clang 18.1.6, C++17, `-O2 -pthread -Wall -Wextra -ffp-contract=off`, compact strategy 2. No fast-math, reassociation, FMA contraction or new build was introduced. Hiddenclip preserves dense/input arithmetic and sequential output reduction, replacing only hidden clipping with the existing vector clipping semantics.

## Frozen plan and workload

`validation-plan.json` was frozen at 2026-10-17T11:43:23.097777+00:00, before performance pairs. Seed **2026101731**; `schedule.json` fixes all 276 blocks and pair orders. Ten paired repeats on the unchanged original 12 positions use 200k/1M nodes and 100/500/1000 ms. Twelve paired repeats on 12 independent composed endgames use those controls plus 200 ms. A separate 12-repeat sentinel receives all six focused controls. Every fixture/control has exactly balanced engine order. Position/control blocks are randomized within repeat rounds. General and focused sentinel observations are reported separately, never pooled.

Both EXEs use CPU0 affinity, one search thread, 16 MiB hash, `NNUEKernel=clip`, identical frozen search switches, no pondering, complete supplied histories and a fresh TT (`game=object()`) per search. Identical 25k-node warm-ups precede primary collection and are excluded. The 30–45-minute estimate and 90-minute benchmark cap were fixed before timing.

| Independent group / fixture | Coverage | Legal moves | Check | Captures |
| --- | --- | --- | --- | --- |
| composition_01 / pawn_opposition | pawn/quiet/few_moves | 5 | False | 0 |
| composition_02 / pawn_wings | pawn/quiet | 13 | False | 0 |
| composition_03 / pawn_race | pawn/promotion | 9 | False | 0 |
| composition_04 / rook_active | rook/quiet | 18 | False | 1 |
| composition_05 / rook_check | rook/in_check | 3 | True | 1 |
| composition_06 / rook_capture | rook/tactical_capture | 17 | False | 1 |
| composition_07 / knight_pawns | minor/knight | 16 | False | 0 |
| composition_08 / bishop_pawns | minor/bishop | 16 | False | 1 |
| composition_09 / bishop_knight | minor/imbalance | 17 | False | 1 |
| composition_10 / queen_rook | piece/imbalance/many_moves | 32 | False | 0 |
| composition_11 / rook_minor | piece/imbalance | 20 | False | 0 |
| composition_12 / queen_checks | piece/queen/many_moves | 29 | False | 1 |

These are legal, nonterminal, hand-composed coverage fixtures, not game/dataset samples, candidate-selected variations, or sealed positions. No multiple positions from one game are counted as independent. Similar material templates can still correlate: intervals describe this convenience suite, not a random population of chess endgames. Full FENs/origins are in the frozen position manifests.

## Environmental controls and telemetry

AC power and the OEM Acer plan were checked before and after **all 276 blocks**; all checks passed. CPU0 affinity was verified for every child search. Quiet/Eco is the last user-confirmed NitroSense preference; the current OEM mode is not independently exposed. No power, CPU priority, application, security or driver setting was changed.

A 0.5-second pre-block load probe pauses above 20% other CPU use, at most three 5-second pauses per block. Any probe/search above 25% flags the entire block, symmetrically. **All observations remain in the primary analysis.** There were 51 pauses and 98/276 flagged blocks (35.5%). Other CPU percent of total logical capacity: median 12.35, range 0.00–62.50. This does not directly measure CPU0 contention.

Process CPU time comes from `GetProcessTimes` around each search; wall time and wall NPS remain primary. Observed CPU deltas are quantized in 15.625-ms increments, and some short-search CPU/wall ratios exceed 1, illustrating accounting resolution/boundary limitations against the high-resolution wall interval. They are not literal CPU utilization readings. CPU accounting includes search/protocol work over the same operation; short-search CPU ratios are diagnostic, not replacements for wall results.

An additional **275 CPU0 Windows counter snapshots** (0 errors) cover 2849/3072 searches within ±10 seconds. Collection began partway through the schedule. Raw timestamps/offsets remain in CSV/JSON; missing samples are explicit. The Windows counter interface is documented by [Microsoft](https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters). `ProcessorFrequency` is not accepted as measured effective MHz; `% Processor Performance` and limit flags are retained as reported diagnostics without an independently calibrated clock conversion. Reliable effective search-core MHz, temperature and thermal-throttling measurements remain unavailable. No thermal or frequency cause is established from these counters.

CIM query wall duration: median 0.306s, maximum 1.868s. Flagged fractions were 39.1% across 23 blocks before counter collection, versus 35.2% across 253 afterward. These unequal windows are diagnostic only; they neither establish nor rule out observer overhead. Short system-CPU deltas also have accounting/interval limitations. A separate three-second process snapshot is preserved in `environment-system-snapshot.json`; it cannot explain all transient flags. No application or thermal cause is inferred.

| Reported CPU0 counter | Median | Range |
| --- | --- | --- |
| PercentPerformanceLimit | 100.0000 | 100.0000–100.0000 |
| PercentProcessorPerformance | 169.0000 | 40.0000–176.0000 |
| PerformanceLimitFlags | 0.0000 | 0.0000–0.0000 |
| ProcessorFrequency | 2100.0000 | 1453.0000–2100.0000 |

`setup-audit.json` discloses pre-measurement fixture/harness corrections and the zero-duration load-probe fix. `discarded.jsonl` preserves one aborted initial first-pair attempt (`0:0`), with **zero captured search records**, caused by that probe error before the first measured search. The subsequent run completed each scheduled pair exactly once; no completed performance measurement was discarded. The plan/position set was not altered after timings began. `events.jsonl` preserves starts/resumes/warm-ups/pauses. No inconvenient performance pair was excluded.

## Statistics and limitations

Primary estimator: `exp(mean(per-position median(log(candidate wall-NPS / baseline wall-NPS))))`. Fixed-node ratios equal inverse elapsed-time ratios because the work is identical. Timed NPS uses **actual total nodes**, including unfinished iterations; reported completed depth/PV can differ without a correctness failure.

The 95% hierarchical bootstrap uses 10,000 draws, resampling position groups and paired repeats within positions. Sentinel intervals resample its repeats only and are explicitly **not across-position confidence intervals**. A separate circular length-two repeat-block bootstrap shares repeat indices across positions to test common temporal shocks. Early/late halves, normalized baseline drift, order subsets, stable-block subsets and leave-one-position-out estimates are sensitivities, not new primary estimators. No old Stage 3 observations enter these estimates. Intervals are unadjusted for multiple comparisons and do not remove systematic scheduling, thermal or frequency bias.

Material means an observed factor below `1/1.03 = 0.970874`, equivalent to >3% additional elapsed time for equal work. For timed searches this is an **equivalent throughput penalty**, not a literal >3% longer time budget. A noisy median alone is not an established defect. The frozen plan distinguishes repeat intervals/consistent controls and orders from isolated short-time noise, and specifies ACCEPTED/REJECTED/INCONCLUSIVE gates before measurement.

## Fresh frozen 12-position suite

| Control | Factor / 95% | CPU-NPS factor | Baseline first / candidate first | Length-2 95% | Stable-block factor |
| --- | --- | --- | --- | --- | --- |
| 200,000 nodes | 1.0574× [1.0342, 1.0889] | 0.9828 | 1.0815 / 1.0461 | [1.0306, 1.0959] | 1.0582 |
| 1,000,000 nodes | 1.0636× [1.0478, 1.0821] | 1.0772 | 1.0649 / 1.0646 | [1.0465, 1.0855] | 1.0606 |
| 100 ms | 1.0841× [1.0509, 1.1114] | 1.0487 | 1.1020 / 1.0691 | [1.0453, 1.1193] | 1.0921 |
| 500 ms | 1.0864× [1.0616, 1.1125] | 1.0730 | 1.0664 / 1.1080 | [1.0594, 1.1137] | 1.0834 |
| 1000 ms | 1.0741× [1.0573, 1.0918] | 1.0771 | 1.0549 / 1.0934 | [1.0552, 1.0950] | 1.0669 |

## Independent endgame suite

| Control | Factor / 95% | CPU-NPS factor | Baseline first / candidate first | Length-2 95% | Stable-block factor |
| --- | --- | --- | --- | --- | --- |
| 200,000 nodes | 1.0419× [1.0153, 1.0611] | 1.0561 | 1.0361 / 1.0362 | [1.0073, 1.0713] | 1.0490 |
| 1,000,000 nodes | 1.0603× [1.0436, 1.0765] | 1.0433 | 1.0629 / 1.0585 | [1.0403, 1.0800] | 1.0642 |
| 100 ms | 1.0576× [1.0301, 1.0813] | 1.0678 | 1.0767 / 1.0340 | [1.0225, 1.0822] | 1.0604 |
| 200 ms | 1.0532× [1.0373, 1.0693] | 1.0531 | 1.0505 / 1.0532 | [1.0332, 1.0705] | 1.0612 |
| 500 ms | 1.0590× [1.0455, 1.0761] | 1.0644 | 1.0506 / 1.0740 | [1.0418, 1.0835] | 1.0618 |
| 1000 ms | 1.0542× [1.0389, 1.0697] | 1.0633 | 1.0508 / 1.0612 | [1.0318, 1.0761] | 1.0606 |

## Original piece-endgame sentinel, focused repeats

| Control | Factor / 95% | CPU-NPS factor | Baseline first / candidate first | Length-2 95% | Stable-block factor |
| --- | --- | --- | --- | --- | --- |
| 200,000 nodes | 1.1032× [1.0210, 1.1833] | 1.1180 | 1.0277 / 1.1599 | [1.0210, 1.1835] | 1.1171 |
| 1,000,000 nodes | 1.0256× [0.9923, 1.0578] | 1.0260 | 1.0171 / 1.0290 | [0.9860, 1.0679] | 1.0256 |
| 100 ms | 1.0559× [1.0049, 1.0843] | 1.0413 | 1.0559 / 1.0511 | [1.0389, 1.0635] | 1.0559 |
| 200 ms | 1.0122× [0.9871, 1.0539] | 0.9979 | 1.0286 / 1.0081 | [0.9986, 1.0486] | 1.0315 |
| 500 ms | 1.0437× [1.0243, 1.0990] | 1.0964 | 1.0820 / 1.0387 | [1.0351, 1.0864] | 1.0387 |
| 1000 ms | 1.0570× [1.0287, 1.1005] | 1.0734 | 1.0558 / 1.0714 | [1.0399, 1.1005] | 1.0558 |

**All intervals in this sentinel table are repeat-only.** FEN: `8/5pk1/6p1/3R4/8/5PK1/6P1/1r6 w - - 0 1`.

## Original anomaly and fresh sentinel diagnosis

Historical Stage 3 general factors were 1.0530 / 1.0642 / 1.0566 / 1.0632 / 1.0768 at 200k / 1M / 100 / 500 / 1000 ms. Its seven sentinel100 factors were 0.9285, 0.9132, 1.0613, 1.0490, 1.1960, 0.9300, 0.9050; median 0.9300, repeat-only interval approximately [0.9132, 1.0613]. That unresolved observation motivated this independent study.

Fresh focused 100-ms sentinel: **1.0559× [1.0049, 1.0843]**; order medians 1.0559 / 1.0511. The separately collected general-suite sentinel gives **1.0921× [0.9732, 1.1309]**, based on ten repeats. Neither is pooled with the historical seven or with the other fresh set.

Focused 100-ms paired factors, in repeat order: 1.0509×, 1.0506×, 0.8831×, 1.0610×, 1.1055×, 0.8870×, 1.2116×, 1.0635×, 1.0628×, 1.0389×, 0.9719×, 1.1252×.

| 100-ms focused sentinel | Baseline | Hiddenclip |
| --- | --- | --- |
| wall_seconds | 0.1020 [0.1019, 0.1023] | 0.1021 [0.1019, 0.1024] |
| seconds | 0.1000 [0.1000, 0.1000] | 0.1000 [0.1000, 0.1000] |
| process_cpu_seconds | 0.0938 [0.0469, 0.1094] | 0.0859 [0.0312, 0.1094] |
| nodes | 293888.0000 [263424.0000, 310528.0000] | 304256.0000 [262656.0000, 327168.0000] |
| depth | 7.0000 [7.0000, 7.0000] | 7.0000 [7.0000, 7.0000] |
| seldepth | 12.0000 [12.0000, 12.0000] | 12.0000 [12.0000, 13.0000] |
| eval_calls | 266655.5000 [239374.0000, 281818.0000] | 276058.0000 [238705.0000, 296930.0000] |
| qnodes | 232740.0000 [209185.0000, 245961.0000] | 240936.5000 [208599.0000, 259851.0000] |

Focused sentinel CPU-NPS factor is 1.0413×; baseline/candidate median CPU/wall utilization fractions are 0.9184 / 0.8410. Paired log-ratio correlation with candidate-minus-baseline background load is -0.34392506071034745; lag-one repeat correlation is -0.4464033361707047. These are small-sample diagnostics, not causal estimates. Actual node totals, completed depths, iterations and counters are preserved. Timing/depth boundaries and scheduler variation can change timed work; unchanged code alone does not prove which caused the old anomaly.

In the fresh focused 100-ms sentinel, **both engines completed depth 7 in every repetition**, and every engine-reported time was 100 ms. Wall time stayed approximately 102 ms. Thus the new individual losses are variation in actual total node completion, not different completed-depth reports or a large protocol delay. There is no fresh evidence identifying the old depth-boundary or thermal mechanism.

## CPU-accounting disagreement investigation

A secondary **read-only** analysis was added after observing that the 200k general-suite CPU-NPS point (0.9828×) disagrees in direction with its wall-NPS point (1.0574×). It does not change the predeclared wall estimator, data, thresholds or decision. CPU intervals use the same grouped/nested bootstrap; sentinel intervals remain repeat-only. The sum-based alternative computes each fixture's total nodes / total CPU time before taking the across-fixture geometric ratio, reducing division of individual quantized deltas.

| Suite / control | Wall factor | CPU factor / diagnostic95 | Sum-based CPU-NPS factor |
| --- | --- | --- | --- |
| general / 200,000 nodes | 1.0574 | 0.9828 [0.9086, 1.0952] | 1.0105 |
| general / 1,000,000 nodes | 1.0636 | 1.0772 [1.0384, 1.1118] | 1.0782 |
| general / 100 ms | 1.0841 | 1.0487 [0.9871, 1.1408] | 1.0637 |
| general / 500 ms | 1.0864 | 1.0730 [1.0460, 1.0967] | 1.0668 |
| general / 1000 ms | 1.0741 | 1.0771 [1.0568, 1.1005] | 1.0804 |
| endgame / 200,000 nodes | 1.0419 | 1.0561 [0.9973, 1.1561] | 1.0587 |
| endgame / 1,000,000 nodes | 1.0603 | 1.0433 [1.0113, 1.0781] | 1.0470 |
| endgame / 100 ms | 1.0576 | 1.0678 [1.0076, 1.1254] | 1.0658 |
| endgame / 200 ms | 1.0532 | 1.0531 [1.0196, 1.0823] | 1.0497 |
| endgame / 500 ms | 1.0590 | 1.0644 [1.0412, 1.0887] | 1.0639 |
| endgame / 1000 ms | 1.0542 | 1.0633 [1.0389, 1.0773] | 1.0545 |
| sentinel / 200,000 nodes | 1.1032 | 1.1180 [1.0000, 1.2500] | 1.0870 |
| sentinel / 1,000,000 nodes | 1.0256 | 1.0260 [0.9747, 1.0862] | 1.0312 |
| sentinel / 100 ms | 1.0559 | 1.0413 [0.9236, 1.3999] | 1.1235 |
| sentinel / 200 ms | 1.0122 | 0.9979 [0.8946, 1.0650] | 0.9803 |
| sentinel / 500 ms | 1.0437 | 1.0964 [0.9709, 1.1334] | 1.0638 |
| sentinel / 1000 ms | 1.0570 | 1.0734 [1.0203, 1.1566] | 1.0813 |

All CPU deltas lie on the observed 15.625-ms grid (0 exceptions); 242 short/other searches have CPU/wall >1. The 200k general CPU interval [0.9086, 1.0952] includes both loss and gain, while its sum-based point is 1.0105×. This discrepancy is unresolved at short-control accounting precision; it does **not** establish opposite sustained throughput. The 1M and 1000-ms general CPU intervals are positive and agree with wall results. No CPU statistic replaces the primary result, and CPU/background correlations share accounting inputs rather than proving a causal mechanism.

## Temporal and execution-order sensitivity

| Suite / control | First / second half | Normalized baseline round range | Lag-1 ratio correlation |
| --- | --- | --- | --- |
| general / 200,000 nodes | 1.0620 / 1.0635 | 0.9150–1.0203 | -0.229041398694952 |
| general / 1,000,000 nodes | 1.0747 / 1.0621 | 0.9632–1.0168 | 0.12397433778560456 |
| general / 100 ms | 1.0878 / 1.0817 | 0.9233–1.0177 | -0.4027108452336761 |
| general / 500 ms | 1.0996 / 1.0776 | 0.9674–1.0224 | -0.5676099499571126 |
| general / 1000 ms | 1.0690 / 1.0844 | 0.9781–1.0202 | 0.2805031920322981 |
| endgame / 200,000 nodes | 1.0268 / 1.0489 | 0.9441–0.9973 | 0.36127554132965845 |
| endgame / 1,000,000 nodes | 1.0658 / 1.0532 | 0.9790–1.0144 | 0.33797475391311527 |
| endgame / 100 ms | 1.0578 / 1.0562 | 0.9350–1.0292 | -0.14626497366457433 |
| endgame / 200 ms | 1.0506 / 1.0598 | 0.9693–1.0190 | -0.19606750855673316 |
| endgame / 500 ms | 1.0666 / 1.0534 | 0.9817–1.0192 | -0.14706506502360056 |
| endgame / 1000 ms | 1.0427 / 1.0641 | 0.9752–1.0222 | 0.44522432590859756 |
| sentinel / 200,000 nodes | 1.1032 / 1.0798 | 0.8499–1.0722 | 0.39305121797733655 |
| sentinel / 1,000,000 nodes | 1.0256 / 1.0366 | 0.9298–1.0381 | 0.041061799707860204 |
| sentinel / 100 ms | 1.0508 / 1.0632 | 0.8959–1.0547 | -0.4464033361707047 |
| sentinel / 200 ms | 1.0081 / 1.0286 | 0.8823–1.0663 | -0.5361171482501856 |
| sentinel / 500 ms | 1.0605 / 1.0437 | 0.9576–1.0882 | -0.06440962476531142 |
| sentinel / 1000 ms | 1.0451 / 1.0856 | 0.9596–1.0869 | -0.22888355989317952 |

Order affects the magnitude at 1000ms: baseline-first 1.0549× versus candidate-first 1.0934×; both favor hiddenclip. The 1M order points are nearly equal (1.0649 / 1.0646). Stable-block long-control factors remain 1.0606 / 1.0669 across all 12 fixtures, each with 81 / 81 retained pairs; these subsets do not replace the primary estimates.

Order-specific grouped points are listed above; per-position order medians are in `analysis.json`. Drift and dependence checks do not establish stationary thermal conditions or eliminate correlated laptop noise. Sparse provider counter snapshots cannot explain individual short searches. CPU and wall diagnostics are shown separately rather than silently exchanging the primary metric.

## Fresh correctness and integrity

Fresh checks passed on all 24 distinct validation positions at 200k nodes, with exact move/score/PV/depth/seldepth/node/counter and completed-iteration parity. All **552 primary fixed-node pairs** also match exactly, reaching their requested node budgets. Eight explicit cancellation checks, four post-stop fixed-work reruns and three classical fixed-work pairs passed. Both benchmark EXEs expose identical UCI defaults/options, and all three preserved production UCI executables report classical as default.

The unchanged Stage 3 receipts retain 161,420 head bit comparisons, 4,352 extra special-value comparisons, 31,876 legal / 26,908 null transitions and restoration tests; these historical tests were reused, not needlessly repeated or claimed fresh. `correctness.json` identifies their hashes and records all fresh gates.

**1,183 protected files unchanged**, including source, active executables, models, previous studies, original EXEs/PDBs and generated headers. Exact identities are checked before/after. No candidate rebuild or production alteration occurred.

## Per-position medians and material regressions

### General

| Fixture | 200,000 nodes | 1,000,000 nodes | 100 ms | 500 ms | 1000 ms |
| --- | --- | --- | --- | --- | --- |
| attack_complex | 1.0613 | 1.0863 | 1.1164 | 1.1514 | 1.0800 |
| castling_rights | 1.1101 | 1.0526 | 1.0392 | 1.0501 | 1.0386 |
| en_passant | 1.1051 | 1.0382 | 1.0651 | 1.1135 | 1.0837 |
| imbalance | 1.0125 | 1.0700 | 1.0557 | 1.1393 | 1.0794 |
| opening | 1.0280 | 1.0534 | 1.0542 | 1.0302 | 1.0327 |
| opening_history | 1.0251 | 1.0724 | 1.1082 | 1.0845 | 1.1057 |
| pawn_endgame | 1.0406 | 1.0488 | 1.0195 | 1.1063 | 1.0597 |
| piece_endgame | 1.0503 | 1.0406 | 1.0921 | 1.0343 | 1.0507 |
| pins | 1.0637 | 1.0962 | 1.1091 | 1.0965 | 1.0935 |
| promotion | 1.0978 | 1.0480 | 1.0961 | 1.0889 | 1.0702 |
| quiet_middlegame | 1.0554 | 1.0815 | 1.1767 | 1.0658 | 1.0981 |
| tactical | 1.0436 | 1.0774 | 1.0849 | 1.0828 | 1.0998 |

### Endgame

| Fixture | 200,000 nodes | 1,000,000 nodes | 100 ms | 200 ms | 500 ms | 1000 ms |
| --- | --- | --- | --- | --- | --- | --- |
| bishop_knight | 1.0364 | 1.0618 | 1.0386 | 1.0753 | 1.0363 | 1.0382 |
| bishop_pawns | 1.0553 | 1.0440 | 1.1175 | 1.0831 | 1.0641 | 1.0712 |
| knight_pawns | 1.0705 | 1.0474 | 1.0511 | 1.0304 | 1.0649 | 1.0639 |
| pawn_opposition | 1.0325 | 1.0734 | 1.0227 | 1.0567 | 1.0617 | 1.0476 |
| pawn_race | 1.0609 | 1.0776 | 1.0823 | 1.0574 | 1.0766 | 1.0630 |
| pawn_wings | 1.0124 | 1.0681 | 1.0608 | 1.0422 | 1.0746 | 1.0366 |
| queen_checks | 1.0343 | 1.0776 | 1.0367 | 1.0301 | 1.0671 | 1.0447 |
| queen_rook | 1.0352 | 1.0622 | 1.0498 | 1.0418 | 1.0422 | 1.0384 |
| rook_active | 1.0635 | 1.0503 | 1.0944 | 1.0572 | 1.0631 | 1.0606 |
| rook_capture | 0.9977 | 1.0323 | 1.0577 | 1.0462 | 1.0620 | 1.0704 |
| rook_check | 1.0527 | 1.0927 | 1.0584 | 1.0513 | 1.0686 | 1.0503 |
| rook_minor | 1.0536 | 1.0383 | 1.0255 | 1.0676 | 1.0278 | 1.0662 |

### Sentinel

| Fixture | 200,000 nodes | 1,000,000 nodes | 100 ms | 200 ms | 500 ms | 1000 ms |
| --- | --- | --- | --- | --- | --- | --- |
| piece_endgame | 1.1032 | 1.0256 | 1.0559 | 1.0122 | 1.0437 | 1.0570 |

Observed material fixture/control medians: **0**; established material regressions: **0**; unresolved concerns: **0**.

Worst ten fixture/control medians, including all observed losses:

| Suite / fixture | Control | Factor | Repeat-only 95% |
| --- | --- | --- | --- |
| endgame / rook_capture | 200,000 nodes | 0.9977 | [0.9429, 1.0715] |
| sentinel / piece_endgame | 200 ms | 1.0122 | [0.9871, 1.0539] |
| endgame / pawn_wings | 200,000 nodes | 1.0124 | [0.9481, 1.1372] |
| general / imbalance | 200,000 nodes | 1.0125 | [0.9194, 1.1444] |
| general / pawn_endgame | 100 ms | 1.0195 | [0.9440, 1.1025] |
| endgame / pawn_opposition | 100 ms | 1.0227 | [0.9305, 1.0812] |
| general / opening_history | 200,000 nodes | 1.0251 | [0.9874, 1.0753] |
| endgame / rook_minor | 100 ms | 1.0255 | [0.9780, 1.0601] |
| sentinel / piece_endgame | 1,000,000 nodes | 1.0256 | [0.9923, 1.0578] |
| endgame / rook_minor | 500 ms | 1.0278 | [0.9983, 1.0646] |

## Predeclared decision gates

| Gate | Pass |
| --- | --- |
| cpu_does_not_contradict | True |
| endgame100_no_convincing_loss | True |
| endgame100_noninferior | True |
| environmental_flags_within_budget | False |
| exact_identities | True |
| fixed_work_exact | True |
| general_long_gain | True |
| general_other_no_convincing_loss | True |
| long_dependence_gain | True |
| long_early_late_gain | True |
| long_orders_positive | True |
| long_stable_gain | True |
| no_established_material_loss | True |
| no_unresolved_material | True |

The thresholds were not adjusted to the observed results. Position/control repeat intervals are unadjusted diagnostics; aggregate grouped intervals and consistency/order/environment checks govern the overall conclusion. No majority-of-wins or Elo shortcut was used.

## Explicit answers and recommendation

1. **Was the original 100-ms slowdown reproducible?** No: the fresh focused median is positive, with its repeat-only 95% lower bound above 1; the historical 7.53% penalty did not reproduce.
2. **Fresh sentinel median and uncertainty?** 1.0559× [1.0049, 1.0843], 12 paired repeats, repeat-only interval; fresh general sentinel 1.0921× [0.9732, 1.1309], separately reported.
3. **Independent endgame systematic slowdown?** 100-ms grouped factor 1.0576× [1.0301, 1.0813]; noninferiority gate (>0.970874 lower bound): True.
4. **Did the frozen suite reproduce the earlier 6–8% gain?** Yes, the independent point estimates reproduce that magnitude. Fresh long-control gains are 6.36% at 1M and 7.41% at 1000 ms. Historical observations are not pooled; formal acceptance remains subject to the environmental gate.
5. **Fixed-node and timed gains?** All five general controls and all six focused controls appear in the separate tables; fixed-node inverse-time factors are equivalent to wall-NPS factors, timed factors use actual nodes.
6. **Execution-order sensitivity?** General 1M baseline-first/candidate-first 1.0649/1.0646; 1000ms 1.0549/1.0934. Both-order positive gate: True.
7. **Did CPU/frequency explain anomalies?** General long-control CPU-NPS points 1.0772/1.0771, versus wall 1.0636/1.0741; both favor hiddenclip in this study. This supports a throughput gain but does not identify the historical cause. No calibrated effective-MHz or thermal attribution is available.
8. **Were fixed-work results identical?** Yes: 552 primary fixed-node pairs plus the fresh correctness suite, including completed iterations.
9. **Any material regressions remaining?** 0 observed medians, 0 established, 0 unresolved; all enumerated above.
10. **Replace Stage 1 as experimental baseline?** INCONCLUSIVE: retain Stage 1; no production promotion.
11. **Next highest-value opportunity?** First resolve the environmental acceptance limitation before replacing the accepted baseline. The unchanged dense matrix multiply remains the largest measured head component (Stage 3 historical profile: 859/1257 head samples, approximately 68%). A separately authorized strict-float dense-kernel/code-generation investigation has the clearest optimization target; preserve operation order and validate whole search. No further validation, Stage 4 or new optimization was started.

## Reproduction and preserved evidence

See workspace `README.md` for exact PowerShell commands. `validation-plan.json`, `schedule.json`, position manifests, `pairs.jsonl`, raw CSV/JSON, per-position CSV, environment/block/CPU telemetry, correctness/provenance receipts and analysis scripts preserve the investigation. `manifest.json` records SHA-256, byte counts and normalized text hashes; original executables/PDBs remain in the preserved Stage 3 artifacts, with byte-identical local archival copies in this workspace's ignored `artifacts/exact-binaries/` and `archived-binaries.json` receipts. Reports and measurements from earlier stages are untouched. No additional games, repeats or follow-up automation are scheduled.
