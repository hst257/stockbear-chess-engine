# StockBear Compact v2 — Whole-Search Throughput Optimization

## Executive summary

The accepted change removes redundant sorted piece-feature metadata maintenance from NNUE child-state updates. At 1M nodes, whole-search wall throughput improved **15.5%**; the selected-position bootstrap range is **12.2–18.8%**. NNUE/classical NPS moved from **69.5% to 80.3%**, closing **35.4%** of the contemporaneously measured throughput gap.

The model, float32 arithmetic order, score contract, search algorithms, pruning, ordering, TT policy, time management and classical evaluation are preserved. Classical remains the UCI/application default. Eager updates remain enabled. No training or NNUE v3 work was performed.

The final release and UBSan builds each matched **240 deterministic search cases** across both evaluators. The full suite reports **1149 passed in 111.60s (0:01:51)**. All native transition/corpus/golden gates passed. The user amended the initial 60-game schedule to **35 completed games at 500ms/move**: 17 complete opening pairs plus one separately reported unpaired game. The first smoke pair remains included.

## Baseline and measurement methodology

Frozen revision `a2fb045ca39e3a5ced430c83a1c3ded15a58941e`; tag `nnue-v2-throughput-baseline-a2fb045`. The untouched rebuilt baseline matched the preserved release's code-section SHA256 `2fcdef4e1aa35e8807b6cb05dbfe752625760e535f241c644e9eaeaa23b70d1e`. Compiler: Zig 0.13.0, C++17, `-O2 -ffp-contract=off`, portable scalar float32; no fast-math, LTO, model precision change or explicit SIMD. CPU: 13th Gen Intel Core i5-13420H, 12 logical processors, Windows/Python 3.11.8. No affinity or frequency lock; no concurrent CPU-heavy experiments.

The same 24 legal FENs from the prior diagnosis cover 12 categories. Final release tests use five trials at 100k/400k/1M nodes and 50/200/1000ms: 2,160 searches, plus a direct five-trial classical A/B check. Run order rotates by position and trial. Each capture uses a fresh game/search TT, Hash=16MB and one search worker; each binary uses the same scalar/incremental/model/search options. Classical is measured in the preserved baseline executable.

Per-position trial medians are aggregated geometrically. Two short mate fixtures, early fixed-node terminations and any sub-10ms trial are excluded from aggregate throughput only; raw records retain everything. Intervals resample selected FENs 10,000 times and are descriptive suite sensitivity, not confidence about arbitrary chess positions. Repeated trials and per-position ranges remain in JSON/CSV. UCI wall time includes communication and fresh TT setup; engine time is separately recorded in milliseconds. Timed trees may differ because faster search reaches more work, so fixed-node results are the primary implementation-speed evidence.

## Profiling findings

Before optimization, 432 serial searches across release/counters/clocks produced identical trees. Total wall: release 43.357s, counters 44.662s, clocks 102.987s. Counter overhead was 3.0%; clock overhead was 137.5%. Clock percentages are **not production runtime shares**.

Windows WPR CPU sampling failed to enable the OS profiling policy (`0xc5585011`). Hardware cache/branch/memory-bandwidth counters were unavailable. Existing scoped clocks, exact logical counters and release differential measurements were used instead. Detailed clocks separately cover move generation, make/unmake, delta construction, state extraction, metadata, rows, copy, root refresh, head, table operations, search bookkeeping and allocations. Quiescence work is identified by node/update counters; overlapping qsearch time is not added to exclusive categories.

| Rank | Candidate cost | Evidence / decision |
| --- | --- | --- |
| 1 | Redundant full sorted piece-feature metadata per edge | Removing it yields the accepted repeatable release improvement; this is the largest demonstrated recoverable cost. |
| 2 | Row-update/delta/state bookkeeping | Still performed in exact feature order; head and row loops remain otherwise unchanged. Differential fusion did not improve eager compact. |
| 3 | NNUE head | Significant instrumented scope, already transposed and fast; no evidence justifying a new SIMD/quantized implementation. |
| 4 | Fully unused frames | Cached deferral bounds replay but adds readiness/storage overhead; direct timing rejected it. |
| 5 | Lane copying | Prior 1.74ns isolated copy and timer distortion do not establish it as the primary bottleneck. No standalone memcpy optimization accepted. |
| 6 | Root refresh / allocations | Per-search setup; root refresh is tiny in the trace. Fresh TT construction is outside profile scopes, but included in wall time. No per-node NNUE allocation introduced. |

Detailed measured scope times and work counts are in [detailed-profile.json](docs/nnue-v2-throughput/detailed-profile.json). They cannot identify physical cache misses or assign a precise release-time percentage to metadata alone. The accepted implementation is a small bundle of metadata/state lookup changes, not a causal Elo allocation.

The identical 24-FEN 400k-node detailed workload used 9,600,000 visits, 7,580,323 evaluations, 9,594,665 updates, 22,052,448 changed rows per perspective and 24 root refreshes. These counts are unchanged. Logical copied payload fell from 3.915GB to 2.514GB. Root stack storage remains 664 bytes/frame and 43,160 bytes total; this optimization does not shrink that stack. The payload estimate includes metadata generated/stored, not a measured physical memcpy or cache-traffic count. [Work summary](docs/nnue-v2-throughput/work-summary.json).

## Optimization experiments

All candidate screening builds passed 96 exact search cases, all kernel-switch checks and the bitwise move/null oracle before timing. Screening: three 400k-node trials. Later alternatives also received direct five-trial duels against eager compact.

| Candidate | Hypothesis and change | Screening wall speed vs baseline | Decision |
| --- | --- | --- | --- |
| merge | Single merge instead of repeated list shifts | 1.010× [0.987, 1.030] | Rejected: gain not established |
| compact | Retain sorted state rows only; preserve full float sums | 1.169× [1.138, 1.200] | Accepted: final verification passed |
| deferred | Cache every materialized intermediate ancestor | 1.135× [1.109, 1.161] | Rejected: slower than eager compact |
| fused | Keep each lane live through ordered row operations | 1.137× [1.098, 1.178] | Rejected: no additional reliable gain |
| compact-small | 24-byte state extraction temporary instead of 152 bytes | 1.175× [1.130, 1.218] | Rejected: smaller temporary, no reliable runtime gain |

Direct speed relative to eager compact (above one favors the alternative):

- deferred: 0.973×, interval [0.955, 0.992].
- fused: 0.990×, interval [0.970, 1.010].
- compact-small: 0.995×, interval [0.979, 1.012].

The search-only invariant is that legal move generation supplies the move, its delta is captured before make, after-move state features retain legal-EP and clean-castling checks, and children use distinct stack storage. Full roots refresh. Subsequent move-derived updates read prior state features; they do not need sorted piece lists. The redundant missing-piece lookup in those lists is removed only in this trusted API. The general full-feature updater retains validation and remains the independent arithmetic reference. Reference/quantized kernels keep the legacy full-metadata path. Kernel selection is immutable within a search; switches refresh roots. No float row arithmetic is reassociated.

Deferral's exact invariant, head-call materialization point, 64-ply worst chain, at-most-once intermediate caching and approximately 11.7KB extra pending storage are documented in [EXPERIMENTS.md](docs/nnue-v2-throughput/EXPERIMENTS.md). It never replays from evaluated ancestors alone. Its row work is bounded by eager work for an identical tree, yet release runtime regressed. Eager updates therefore remain the production path. Rejected prototypes are compile-time options and omitted from ordinary builds.

## Final fixed-node benchmarks

| Nodes | Eligible FENs | Wall speedup | Selected-FEN 95% interval | NNUE/classical NPS before→after | Gap closed |
| --- | --- | --- | --- | --- | --- |
| 100,000 | 22 | 1.152× | [1.112, 1.191] | 68.4%→79.4% | 35.0% |
| 400,000 | 22 | 1.147× | [1.115, 1.181] | 69.8%→80.3% | 34.9% |
| 1,000,000 | 22 | 1.155× | [1.122, 1.188] | 69.5%→80.3% | 35.4% |

A separate counter-only pass measures work at every budget, matching the final release tree and pre-edit work counts exactly. Totals below include all 24 fixtures; these instrumented times are excluded from performance estimates.

| Requested nodes | Evaluations | Accumulator updates | Root refreshes | Changed rows / perspective |
| --- | --- | --- | --- | --- |
| 100,000 | 1,913,518 | 2,397,706 | 24 | 5,494,393 |
| 400,000 | 7,580,323 | 9,594,665 | 24 | 22,052,448 |
| 1,000,000 | 18,588,643 | 23,989,946 | 24 | 55,212,990 |

Gap closure is `(optimized NNUE/classical − baseline NNUE/classical) / (1 − baseline NNUE/classical)`, using contemporaneous paired suite measurements. Historical 66–72% diagnosis values are context, not substituted into this formula. The target of 85–90% was aspirational, not an acceptance threshold.

| FEN | 100k wall speed | 400k wall speed | 1M wall speed | 1M baseline→optimized median ms |
| --- | --- | --- | --- | --- |
| start | 1.053× | 1.093× | 1.221× | 919.91→753.24 |
| queen_gambit | 1.365× | 1.168× | 1.262× | 977.49→774.29 |
| old_middle | 1.130× | 1.224× | 1.174× | 824.01→701.73 |
| italian_structure | 1.216× | 1.260× | 1.222× | 831.15→680.28 |
| kiwipete | 1.139× | 1.174× | 1.283× | 1110.90→865.59 |
| pins | 1.323× | 1.260× | 1.260× | 817.24→648.71 |
| attack_complex | 1.173× | 1.156× | 1.177× | 854.43→725.95 |
| mate_net | 1.351×* | 1.215×* | 1.170×* | 526.04→449.64 |
| queen_rooks | 1.066× | 1.115× | 1.161× | 636.91→548.79 |
| rook_minors | 1.224× | 1.133× | 1.219× | 602.53→494.14 |
| old_pawns | 1.244× | 1.152× | 1.073× | 472.71→440.50 |
| opposed_pawns | 1.085× | 1.173× | 1.099× | 485.32→441.51 |
| rooks | 1.188× | 1.036× | 1.080× | 606.42→561.34 |
| rook_bishop | 1.119× | 1.149× | 1.159× | 728.50→628.79 |
| outside_passer | 1.225× | 1.060× | 1.134× | 545.72→481.15 |
| rook_pawn | 0.941× | 1.027× | 1.121× | 442.09→394.52 |
| promotion_race | 1.061× | 1.031× | 1.017× | 588.62→578.59 |
| underpromotion_perft | 1.108× | 1.169× | 1.117× | 756.09→677.19 |
| white_blocked | 1.097× | 1.137× | 1.082× | 412.95→381.66 |
| black_blocked | 1.054× | 1.040× | 0.997× | 399.10→400.36 |
| defend_mate_net | 1.249×* | 1.141×* | 1.155×* | 525.83→455.36 |
| defend_complex | 1.167× | 1.167× | 1.235× | 791.44→640.87 |
| carlsbad | 1.228× | 1.299× | 1.199× | 647.42→539.85 |
| locked_center | 1.224× | 1.275× | 1.179× | 602.10→510.75 |

Asterisks mark excluded short/early-terminating fixtures. All values remain observable; they are not pooled as reliable throughput estimates.

- 100,000 nodes: position speedup min/median/max 0.941/1.153/1.365×; median regressions: rook_pawn. Individual reversals may reflect noise; no per-FEN significance claim is made.
- 400,000 nodes: position speedup min/median/max 1.027/1.154/1.299×; median regressions: none. Individual reversals may reflect noise; no per-FEN significance claim is made.
- 1,000,000 nodes: position speedup min/median/max 0.997/1.167/1.283×; median regressions: black_blocked. Individual reversals may reflect noise; no per-FEN significance claim is made.

Across the individual eligible 1M-node FEN/trial comparisons, speedup min/median/max was 0.909/1.159/1.529×. These repeated measurements expose system variation; they are not independent position samples.

## Final fixed-time benchmarks

| ms | Eligible FENs | Baseline NNUE/classical NPS | Optimized NNUE/classical NPS | NNUE NPS gain | Mean completed-depth change |
| --- | --- | --- | --- | --- | --- |
| 50 | 22 | 68.2% | 80.3% | 17.8% | +0.155 |
| 200 | 22 | 68.4% | 79.7% | 16.4% | +0.127 |
| 1000 | 22 | 69.6% | 81.8% | 17.6% | +0.082 |

Means below use all five trials on 22 non-mate FENs; each cell is baseline NNUE / optimized NNUE.

| ms | Nodes searched | Actual wall ms | Engine ms | Completed depth | ID root-move changes |
| --- | --- | --- | --- | --- | --- |
| 50 | 72374 / 85320 | 53.49 / 53.45 | 50.00 / 50.00 | 6.75 / 6.91 | 1.39 / 1.40 |
| 200 | 302850 / 350541 | 203.28 / 203.29 | 200.00 / 200.00 | 8.23 / 8.35 | 1.68 / 1.74 |
| 1000 | 1618183 / 1897819 | 1003.29 / 1003.33 | 1000.02 / 1000.00 | 9.75 / 9.84 | 2.15 / 2.19 |

Fixed-time moves, scores, completed depths and PVs may differ because the implementation searches farther. This is expected and does not weaken the exact fixed-work gates. Complete per-iteration stability, nodes and timing are retained in raw JSON. More nominal depth or changed moves alone are not a playing-strength claim. Windows process CPU counters accompany final release trials; CPU/wall ratios include worker and small UCI activity and have OS accounting granularity. No extra search thread is added.

At 1M nodes, pooled process CPU/wall utilization was 96.8% baseline NNUE, 97.3% optimized NNUE and 96.9% frozen classical, where 100% denotes one logical CPU. [CPU details](docs/nnue-v2-throughput/cpu-summary.json).

## Correctness and classical preservation

- Baseline tests: 1144 passed in 107.28s (0:01:47). Final tests: 1149 passed in 111.60s (0:01:51).
- Release and UBSan each: 24 FENs × two evaluators × depths 4/6 and 100k/400k/1M nodes = 240 exact cases; identical best moves, scores, PVs, nodes, selective depths and all search counters. The final repeated fixed-node benchmark additionally checks every paired NNUE result.
- Native bitwise oracle: 31,876 real/sibling move transitions and 26,908 null transitions, preserving every float lane and final score bit against the retained full-metadata implementation. Includes captures, promotions, castling, legal/illegal-EP state distinctions, long walks, sibling restoration and root refreshes.
- Held-out/random/extreme corpus: 22,165 outputs, maximum reference difference 0cp. Trained goldens: 128, maximum difference 0.000201686cp. Generic scalar and integer transition oracles also pass; head extreme/clipping checks remain enabled.
- UCI defaults identical; classical stays default. Kernel switching, evaluator switching, fresh TT/root refresh, 12 cancellations per checked build and five terminal/draw-history cases pass. GUI worker/time-preset/stale-result checks pass; the [minimum-size frame](docs/nnue-v2-throughput/gui-minimum.png) was inspected. A separate native Windows launch and [desktop frame](docs/nnue-v2-throughput/gui-desktop.png) are recorded in [desktop verification](docs/nnue-v2-throughput/desktop-verification.json).
- Classical evaluator/constants, search-policy header, transposition implementation and UCI main source are byte-identical to the baseline source snapshot. Shared search edits are confined to NNUE state preparation/evaluation guards; all pruning, bounds, ordering, draw and time logic remain unchanged. Integrated `.text` changes because the NNUE call path changes, so final binary-wide code equality is not claimed; exact classical trees and the complete suite are the behavioral gates.
- Normal application executable rebuilt with its original embedded v1 model and classical default, preserving the old executable separately. 32 additional fixed-budget v1 runtime comparisons matched exactly. Compact v2 was used explicitly for every study measurement and the native desktop launch; no model-default migration is implied.
- Direct classical release timing: 1.015× baseline/final wall speed, selected-FEN interval [1.000, 1.029]. This measures code-layout/system effects separately; it is not included in the frozen-classical denominator.

UBSan ran the full parity, corpus and transition gates with no detected error. AddressSanitizer could not be built for the installed Windows compiler/target runtime; the exact failure is retained in `asan-availability.json`. No ASan pass is claimed, and no sanitizer runtime failure was ignored.

| Identity | SHA256 |
| --- | --- |
| Compact v2 model | `788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7` |
| Untouched baseline executable | `f2258efc377dfef5738b5a78dd61eb291b9fc23fdc38a6be4fbbbd87fe256f97` |
| Final executable | `765419454f3453873cc6e36cf0cab0434fb9e0f16aace4a83560f9b0aaff0595` |

Full compiler flags, source SHA256 maps, executable identities and platform metadata are recorded with every build/measurement. `--nnue-update compact` is now the build default; `--nnue-update legacy` selects the retained reference path. No default evaluator/model export/training configuration changed.

## Bounded playing-strength validation

The original 60-game schedule was stopped at **35 completed games at 500ms/move**, following the user's mid-run instruction. The first 34 games comprise 17 evaluator-neutral opening pairs with reversed colors; game 35 is the White half of pair 18. Optimized NNUE vs frozen baseline NNUE, identical model/search settings. The smoke pair remains included. Full 35-game W–D–L–U: **14–13–8–0**; completed-game score **58.6%**; unknown-outcome bounds **58.6%–58.6%**.

**Paired analysis uses only games 1–34:** W–D–L–U [13, 13, 8, 0], score 57.4%. Pair-resampled 95% censoring sensitivity envelope: **48.5%–66.2%**. Complete-pair bootstrap: 17 pairs, interval [0.4852941176470588, 0.6617647058823529]. Family-cluster complete-pair interval: [0.4852941176470588, 0.6617647058823529]. Conditional paired-game Elo estimate: +51.5; this small validation does **not** establish a universal Elo advantage.

**Unpaired game 35:** optimized played white; result 1-0 (win), 167 total plies, checkmate. It contributes to full descriptive WDL/NPS only and is excluded from paired uncertainty/Elo. It is not imputed as a complete opening pair.

Game NPS optimized/baseline: 1.762M/1.492M; mean completed depth 8.15/8.04. These are different played positions/trees, so fixed-FEN comparisons are the stronger implementation evidence. Terminations: {'checkmate': 22, 'threefold_repetition': 12, 'insufficient_material': 1}. Total recorded game wall time 34.0 minutes.

Claimable draw rules and the fixed 240 searched-ply cap were used without evaluation adjudication. Caps remain unfinished. The 35-game stop was a human runtime amendment, not an automatic decision from outcomes. The original 60-game plan/checkpoint is retained alongside the amendment; no additional completed games or extra classical tournament occurred. Independent JSON/PGN replay verifies every move, color, complete/partial opening pair, terminal result and executable hash. Only 17 complete pairs, selected openings and a mid-run human stop limit generalization and nominal uncertainty coverage. The study asks whether a semantics-preserving speed improvement produces practical search opportunities; it does not retest the neural model against classical at scale.

## Answers and next steps

1. **Largest recoverable overhead:** redundant full sorted piece-feature metadata maintenance on move-derived child updates. The release differential, not a microbenchmark or distorted timer share, establishes the useful target.
2. **Largest verified optimization:** eager compact state metadata, 15.5% whole-search wall throughput gain at 1M nodes. Other independent experiments did not justify production adoption.
3. **Gap closed:** 35.4% at 1M nodes; the remaining measured NNUE/classical NPS gap is 19.7%. Per-budget values appear above; no Elo gain is inferred from this formula.
4. **Regressions:** all deterministic behaviors remain identical. Median timing regressions, trial variation and rejected slower experiments are explicitly listed. Deferral and fused loops stay experimental.
5. **Further NNUE optimization:** possible, but use the remaining whole-search release profile. Current results do not justify a large lazy redesign or blindly restoring prior SIMD/quantization prototypes. Preserve this v2 engine as a reference and demand repeated gains for any new candidate.
6. **Ready for king-relative v3?** Yes for a separately versioned research experiment with preserved v2 fallback, trained-feature contracts, grouped holdout, native parity and paired strength/throughput validation. This report does not prove king-relative features fix the earlier match gap. No v3 training or implementation starts here.

## Evidence and reproduction

[Study protocol and commands](docs/nnue-v2-throughput/README.md) · [Experiment contracts](docs/nnue-v2-throughput/EXPERIMENTS.md) · [Fixed-node JSON](docs/nnue-v2-throughput/benchmark-final.json) · [Fixed-node CSV](docs/nnue-v2-throughput/benchmark-final-summary.csv) · [Timed JSON](docs/nnue-v2-throughput/benchmark-final-time.json) · [Timed CSV](docs/nnue-v2-throughput/benchmark-final-time-summary.csv) · [Verification](docs/nnue-v2-throughput/verification-summary.json) · [Match summary](docs/nnue-v2-throughput/validation-summary.json) · [Match PGN](docs/nnue-v2-throughput/validation-500ms.pgn) · [Manifest](docs/nnue-v2-throughput/output-manifest.json).

[Throughput figures](docs/nnue-v2-throughput/throughput.png) · [Vector figures](docs/nnue-v2-throughput/throughput.svg). Original research files and models remain separate. Build labels/binaries are immutable within the study; use fresh labels and paths for a new experiment. Generated native builds/logs/source snapshots are local under `artifacts/nnue-v2-throughput/`; committed raw evidence and report inputs are in the linked study directory.
