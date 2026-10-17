# StockBear — Stage 1 Float32 NNUE Head Optimization

Date: 17 October 2026. Branch: `codex/nnue-stage1-float-head`.
Workspace: `nnue-optimization-stage1-20261017/`.

## Executive summary

**ACCEPTED: verified whole-engine improvement, retained as an isolated experiment. The active engine was not replaced.** Classical remains the default, including in the experimental executable.

The single branchless-input-preclip candidate improved 1,000,000-node throughput by **1.502× (+50.2%)**, with a position-grouped hierarchical 95% bootstrap interval **1.448–1.579×**. This corresponds to approximately **33.4% less wall time** for identical fixed work, not 50% less time. At 1,000 ms, paired wall-NPS improved **1.578× (+57.8%)**. All five control intervals exclude no gain; every position/control median is positive, with a minimum **1.329×**.

Head outputs passed **161,420 bitwise comparisons**, including signed-zero/extreme-finite/NaN cases. Both native transition oracles, original-model goldens, 147 existing targeted tests and all fixed-work search comparisons passed. **713 protected files** remained unchanged.

Results are conditional on this fixed fixture suite and the observed Quiet/Eco laptop conditions. Background load varied and temperature telemetry was unavailable. The effect is large compared with observed run variation, but these measurements do not establish Elo, superiority over classical or a universal speedup.

## Original bottleneck and chosen transformation

The preceding native profile attributed 52.90% of execution to the float head and 12.74% to recognizable accumulator maintenance. The old kernel already emitted YMM multiply/add instructions. Its input clamps nevertheless involved data-dependent control flow, and varying-frame latency increased sharply.

This stage tested **one variant only**: materialize the 128 perspective-ordered clipped inputs into a 64-byte-aligned float buffer, using AVX min/max with deliberately ordered operands. Then consume that buffer with the existing transposed weights and 32 independent hidden-neuron accumulations. A flat 128-input loop replaces the equivalent two perspective loops. Hidden clipping, sequential output reduction, scaling, CP rounding and mate clamp are unchanged.

There is no FMA, reassociation, fast-math, zero skipping, quantization, accumulator change, search-policy change, weight modification or architecture change. No additional optimization variants were needed or combined after inspecting results.

## Exact source changes and isolation

Production `engine/src/` is unchanged. The experiment contains:

* `stage1_head.hpp`: the optional input transformation and otherwise ordered float head.
* `variant.patch`: changes made only to source copies of `nnue.cpp` and `main.cpp` under `artifacts/variant-source`.
* `nnue.cpp` copy: adds the `clip` selector, an AVX2/OS-state capability guard and truthful effective-kernel reporting. The original scalar/reference/integer branches remain available.
* `main.cpp` copy: advertises `clip` as an additional UCI choice. It does not alter evaluator defaults or search settings.

`NNUEKernel=clip` explicitly selects the experimental route. `NNUEKernel=scalar` selects the old head. A new process with `CHESSLAB_DISABLE_SIMD=1` falls back to the original route and reports `scalar`; that path was tested. `auto` still selects the original scalar-named head. This guard does not turn the existing host-feature build into a generally portable binary for old CPUs.

The 64/32 export remains SHA-256 `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`. The selected checkpoint, active executable, original v2/v3 models, old reports and tournament records are protected by the inventory. Generated headers were copied unchanged from the profiling workspace, avoiding a new export or quantization step. No training/sealed-test data was accessed.

## Numerical and search verification

For `_mm256_max_ps(zero,input)` followed by `_mm256_min_ps(one,result)`, the input/result occupies the second operand. That preserves the tested original clamp behavior for unordered/equal inputs, including negative zero and NaN payloads. The alternative operand order would not be interchangeable.

The parity harness compares the new route against the retained original head, preserving all per-neuron and output operation order. It covers:

* **256 existing golden FENs**, plus opening/middlegame/endgame fixtures and both turns.
* Deterministic legal walks with **32,679 moves**, **27,232 null transitions**, captures, 89 castlings, 375 promotions, 41 en-passant moves and 13,952 king moves. Parent accumulators and boards are checked after sibling/null restoration.
* 20,000 seeded arbitrary finite accumulator patterns under both perspective orders, clipping boundaries, subnormals, maximum finite values and signed zeros.
* **1,920 exact special-value clipping-lane comparisons**, including positive/negative infinity and quiet/signaling NaNs; **4 NaN head-output bit comparisons** also match. Finite head comparisons include exact White CP conversion. Non-finite head results are not sent to integer `lround`.
* Independent boundary assertions for the unchanged mate clamp and ties-away-from-zero rounding. Artificial CP boundary inputs test the conversion expression; they are not claimed reachable through this model's weights.

The existing native transition oracle passes independently in **both binaries**: **31,876 move transitions + 26,908 null transitions** per binary, bitwise exact. The original 32/16 model's **128 golden scores** pass using existing immutable headers; explicitly selecting either `scalar` or `clip` produces identical native results. Those model-specific expected scores were not applied to 64/32. The 256 golden FENs are additional input positions for 64/32 parity.

Existing pytest checks: **147 passed, 13 deselected**, covering trained goldens, feature contract, incremental-versus-rebuild searches and terminal precedence on the isolated original-model compatibility build. Its default route remains scalar; the explicit `clip` CLI golden checks and the 64/32 native harness separately exercise the candidate. Five terminal/draw/mate fixtures pass with `clip`; classical fixed-node decisions match on all 12 fixtures with zero NNUE calls.

Preflight compares baseline, optimized, scalar fallback and the frozen tournament executable at depth 5 and 200,000 nodes: **24 four-build groups** match move, CP/mate score, PV, nodes, counters, depth and seldepth. Full performance runs add **168 paired fixed-node comparisons** at 200k/1M nodes, all exact. Legal moves/PVs are validated by the existing capture infrastructure.

Exact decision equivalence is a **fixed-work** claim. At fixed time, faster execution can complete deeper iterations and select a different move; this is not numerical drift. No GUI test or active-engine installation was performed.

## Compiler and generated machine code

Toolchain: Zig 0.13.0 / bundled Clang 18.1.6, Windows x64. Both builds use identical C++17 `-O2 -pthread -Wall -Wextra -ffp-contract=off` settings, compact accumulator strategy 2, no LTO, and the same copied weights. The assembly's embedded compiler record reports `x86-64` with effective host ISA features including AVX2. Merely looking at the CPU-name string would miss those enabled features.

| Property | Original | Experimental dispatcher |
|---|---:|---:|
| PDB function size | 2,750 bytes | 3,527 bytes |
| Stack allocation in function prologue | 1,008 bytes | 1,120 bytes |
| Static vector input maximum instructions | 0 | 16 |
| Static vector input minimum instructions | 0 | 16 |
| FMA instructions | 0 | 0 |
| Annotated spills / reloads, complete dispatcher | 17 / 17 | 17 / 17 |

The optimized input block uses vector max/min and stores instead of per-input conditional branches; the dense loop still uses YMM multiply/add operations. The hidden/output clamp remains unchanged. The variant is inlined into `nnue_side_to_move`; it does not add a heap allocation. Existing accumulator storage is unchanged. The explicit 512-byte input buffer increases the function's measured stack allocation by only 112 bytes because stack-slot lifetimes overlap existing branches.

The dispatcher **grows** because it retains the complete original and integer fallback paths. Its total static branch count also grows; that is not the dynamic branch behavior of the selected optimized path. Spill annotations include other branches and callee-save handling and cannot establish hot-path spill cost. Full assembly/PDB and stripped instruction excerpts are retained. Cache misses, dynamic branch misses, retired instructions and cycles were not measured.

## Head microbenchmarks

Seven paired rotated-order passes; 10,000 warmup and 200,000 timed calls per batch. The same fixed-seed legal-walk frames are prepared before timing in both binaries. Checksums match across every paired batch. A volatile checksum and compiler fences consume outputs. The timer excludes startup, frame construction and weight refresh.

| Rotating frames | Original ns, median [IQR] | Optimized ns, median [IQR] | Median paired speedup |
|---|---:|---:|---:|
| 1 | 138.69 [134.65–141.70] | 116.29 [114.03–143.53] | 1.115× |
| 32 | 147.39 [143.21–154.03] | 134.38 [131.40–138.85] | 1.134× |
| 128 | 425.98 [418.48–438.80] | 130.62 [129.15–135.27] | 3.186× |
| 512 | 627.62 [599.45–649.14] | 145.52 [138.97–166.27] | 4.313× |

Speedups use paired same-pass ratios; they need not equal the ratio of the separately displayed latency medians. Each working set is one fixed corpus, not seven independent samples of chess positions. The 512 full frames occupy 602,112 bytes; working-set size changes both activation variation and locality. No cache-miss or branch-miss attribution is inferred from those sizes alone.

The separate 12-FEN repeated-root benchmark also has positive position medians throughout: the weakest median ratio is **1.125×**. Its complete seven-pass per-FEN distributions are in `analysis.json`. Correctness probes include diverse finite activation patterns; no synthetic pattern is substituted for full-search performance acceptance.

## Full-search benchmarks and uncertainty

The frozen 12-position profiling suite, histories, production search options and 16 MiB hash are identical. One search thread, CPU0 affinity, no pondering, fresh search TT and one active engine search at a time. Seven paired rotated passes × 12 positions × five controls × two binaries = **840 searches**, with no extension based on results.

Primary statistic: compute the median paired wall-NPS ratio for each position, then the geometric mean across positions. For fixed-node searches that is equivalently the baseline/optimized wall-time ratio because exact node counts match. The hierarchical 95% bootstrap resamples positions, then paired repetitions within each sampled position, using 10,000 draws and seed 20261017. Repeats are not treated as independent chess positions. Intervals are descriptive for this selected fixed suite and observed conditions, not universal workload guarantees or strength confidence intervals.

| Control | Paired whole-search factor [grouped 95% interval] | Throughput gain | Cross-position median wall NPS, original / optimized, M/s | Median completed depth, original / optimized |
|---|---:|---:|---:|---:|
| 200,000 nodes | 1.467× [1.418–1.534] | +46.7% | 1.482 / 2.164 | 7 / 7 |
| 1,000,000 nodes | 1.502× [1.448–1.579] | +50.2% | 1.594 / 2.453 | 8 / 8 |
| 100 ms | 1.522× [1.443–1.610] | +52.2% | 1.424 / 2.259 | 6 / 7 |
| 500 ms | 1.541× [1.475–1.596] | +54.1% | 1.609 / 2.554 | 8 / 8 |
| 1,000 ms | 1.578× [1.506–1.651] | +57.8% | 1.670 / 2.772 | 8.5 / 9 |

NPS medians in the fourth column summarize different positions; dividing them is not the paired estimator. Raw records retain actual nodes, engine/wall elapsed time, reported/wall NPS, evaluation calls, quiescence nodes, all search counters and saved moves/scores/PVs. Fixed-node work is identical. Timed searches include unfinished iteration work while reporting the last completed decision.

### Per-position median paired throughput factors

| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1,000 ms |
|---|---:|---:|---:|---:|---:|
| opening | 1.353× | 1.437× | 1.409× | 1.424× | 1.437× |
| quiet_middlegame | 1.447× | 1.504× | 1.458× | 1.556× | 1.684× |
| tactical | 1.442× | 1.454× | 1.466× | 1.497× | 1.491× |
| pawn_endgame | 1.329× | 1.363× | 1.407× | 1.373× | 1.399× |
| piece_endgame | 1.647× | 1.748× | 1.743× | 1.627× | 1.689× |
| imbalance | 1.447× | 1.458× | 1.513× | 1.616× | 1.614× |
| castling_rights | 1.662× | 1.679× | 1.802× | 1.666× | 1.821× |
| promotion | 1.446× | 1.403× | 1.340× | 1.434× | 1.486× |
| en_passant | 1.566× | 1.532× | 1.685× | 1.642× | 1.690× |
| pins | 1.457× | 1.534× | 1.467× | 1.553× | 1.705× |
| attack_complex | 1.417× | 1.504× | 1.570× | 1.509× | 1.517× |
| opening_history | 1.428× | 1.447× | 1.475× | 1.628× | 1.462× |

No position/control median regressed. `search-per-position.csv` includes paired IQRs and all per-position performance/depth/call summaries. Median within-position repeat CVs (original / optimized) are **200,000 nodes: 5.4% / 6.3%; 1,000,000 nodes: 4.9% / 7.0%; 100 ms: 6.9% / 8.7%; 500 ms: 6.0% / 8.7%; 1,000 ms: 4.9% / 5.4%**. These are meaningful noise levels, but are much smaller than the approximately 47–58% grouped throughput gains.

Order sensitivity check, median pair factor with baseline-first / variant-first: **200,000 nodes: 1.443 / 1.462×; 1,000,000 nodes: 1.473 / 1.493×; 100 ms: 1.470 / 1.473×; 500 ms: 1.500 / 1.563×; 1,000 ms: 1.556 / 1.599×**. Both order subsets show a gain. Controls are related and intervals are not a multiple-comparison-adjusted family; the predeclared 1M-node result is the primary decision, with other controls corroborating it.

## Environmental controls and limitations

AC online before/after; the OEM Acer power scheme and last user-confirmed **Quiet/Eco** profile were not changed. The profile cannot be verified from the Windows power scheme alone. CPU: i5-13420H, 8 cores / 12 logical processors. Before/after aggregate frequency snapshots: 1776 / 1776 MHz, not measured search-core boost frequency. Temperature telemetry was unavailable; thermal stability cannot be claimed directly.

There were no concurrent agent-started CPU benchmarks. Other user/system activity was not stopped. Across 84 complete-position segments, estimated background CPU usage after subtracting benchmark processes had median **10.40%**, IQR **7.73–13.94%**, range **3.55–24.61% of total logical capacity**. This does not reveal CPU0/sibling contention. Background activity and frequency variation limit precise clean-system forecasts. Paired rotation, broad position gains and effect size support the experimental acceptance despite that limitation; the report does not advertise a controlled idle-machine percentage.

## Remaining bottleneck

A bounded post-change own-child native sample repeats the established four-position method: 24 total 1.5-second searches, half sampled, after the performance schedule. It records **4,069 valid instruction pointers**, with **2 failed context/suspension attempts omitted**. Every successful suspension is paired with resumption; all searches finish. Median suspension/read interval is 42.0 μs, with a scheduling outlier up to 11.93 ms. Sampled/unsampled per-position NPS ratios range 0.968–1.001. This is a coarse hotspot estimate, not exact timing or hardware counters.

The optimized float head remains the largest named function at **32.37%** of samples. Recognizable accumulator maintenance is approximately **19.32%**, with other work approximately **48.32%**. Ordering/SEE are substantial secondary costs. These shares use a limited separate sample and should not be treated as a precise matched subtraction from the historical 52.90% profile. Debug line attribution maps much of the inlined new head to the dispatcher call site, so it does not separate remaining dense and hidden-clipping time.

The remaining head still performs the required dense arithmetic, hidden clipping and sequential output reduction. Accumulator bookkeeping now occupies a larger relative share. A separately approved Stage 2 maintenance experiment has a measurable target, but this stage does not change it.

## Acceptance and recommendation

**ACCEPTED as an isolated experimental implementation.** All numerical/transition/restoration gates pass; all fixed-work search results match; representative rotating-frame heads and full-search controls improve; every grouped lower interval exceeds one; no fixture median regresses. Only one proposed transformation was tested. No optimization variant was rejected or silently combined with another one.

Two harness/tooling details were corrected during verification: Python-chess can represent UCI `0000` as a falsey null Move rather than `None`, and cached Zig verbose invocations can emit no command trace. Neither correction changes a head, model or benchmark result. Local PDB lookup initially missed `engine.pdb` after the EXE was renamed for sampling; the correct filename was supplied and the **saved samples were resolved without rerunning searches**. Initial unresolved symbol output is retained for audit.

Keep the optimized binary and `clip` option isolated. **Do not replace the active engine or change the default evaluator without explicit promotion approval.** Accept this Stage 1 result; Stage 2 may follow independently after authorization. No Elo or tournament claim is made, and no games were run.

## Artifacts and reproduction

The workspace README gives exact PowerShell build, validation and bounded reproduction commands. `variant.patch`, `stage1_head.hpp` and harness scripts are committed. Raw evidence: `correctness.json`, `regressions.json`, `pytest.log`, `micro.json`, `search.json`, `analysis.json`, `search-per-position.csv`, `assembly-audit.json`, native samples/symbols and environment records. Ignored `artifacts/` retains baseline/optimized binaries, copied source/headers, PDB, full generated assembly and logs on the project drive.

`validation.json`, before/after protected hashes and `manifest.json` provide integrity receipts; text hashes include LF-normalized forms for Git line-ending conversion. The report is mirrored in the experiment directory. No training, new labels, quantization, search changes, sealed-test access, tournaments or active-engine promotion occurred.
