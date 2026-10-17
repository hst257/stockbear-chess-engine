"""Render the final report strictly from the completed frozen measurements."""
import statistics as s
import experiment as p

a=p.common.load(p.ROOT/'analysis.json')
c=p.common.load(p.ROOT/'correctness.json')
r=p.common.load(p.ROOT/'regressions.json')
asm=p.common.load(p.ROOT/'assembly-audit.json')
before=p.common.load(p.ROOT/'environment-before.json')
after=p.common.load(p.ROOT/'environment-after.json')
p.preserve()
preservation=p.common.load(p.ROOT/'preservation-after.json')
primary=next(v for v in a['search'] if v['mode']=='nodes' and v['budget']==1000000)
timed=next(v for v in a['search'] if v['mode']=='time' and v['budget']==1000)
micro_rows=[]
for v in a['micro']:
    micro_rows.append(f"| {v['frames']} | {v['baseline']['median']:.2f} [{v['baseline']['q1']:.2f}–{v['baseline']['q3']:.2f}] | {v['variant']['median']:.2f} [{v['variant']['q1']:.2f}–{v['variant']['q3']:.2f}] | {v['paired_speedup']['median']:.3f}× |")
search_rows=[]
for v in a['search']:
    name=f"{v['budget']:,} nodes" if v['mode']=='nodes' else f"{v['budget']:,} ms"
    lo,hi=v['hierarchical_grouped_bootstrap95']
    search_rows.append(f"| {name} | {v['geomean_paired_speedup']:.3f}× [{lo:.3f}–{hi:.3f}] | +{v['gain_percent']:.1f}% | {v['baseline']['wall_nps_position_medians']['median']/1e6:.3f} / {v['variant']['wall_nps_position_medians']['median']/1e6:.3f} | {v['baseline']['depth_position_medians']['median']:g} / {v['variant']['depth_position_medians']['median']:g} |")
position_rows=[]
for row in p.common.load(p.ROOT/'positions.json'):
    selected=[v for v in a['per_position'] if v['position']==row['id']]
    values=[]
    for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
        v=next(v for v in selected if v['mode']==mode and v['budget']==budget)
        values.append(f"{v['paired_speedup']['median']:.3f}×")
    position_rows.append('| '+row['id']+' | '+' | '.join(values)+' |')
n=a['native'];head=c['head_parity'];load=a['background_load']['other_cpu_percent_estimate']
fn=asm['pdb_function_sizes']
source=asm['variant']
minimum=min(v['paired_speedup']['median'] for v in a['per_position'])
orders='; '.join(f"{v['budget']:,}{' nodes' if v['mode']=='nodes' else ' ms'}: {v['order_median_speedups']['baseline_first']:.3f} / {v['order_median_speedups']['variant_first']:.3f}×" for v in a['search'])
cv='; '.join(f"{v['budget']:,}{' nodes' if v['mode']=='nodes' else ' ms'}: {100*v['baseline']['repeat_cv']['median']:.1f}% / {100*v['variant']['repeat_cv']['median']:.1f}%" for v in a['search'])
report=f'''# StockBear — Stage 1 Float32 NNUE Head Optimization

Date: 17 October 2026. Branch: `codex/nnue-stage1-float-head`.
Workspace: `nnue-optimization-stage1-20261017/`.

## Executive summary

**{a['status']}: verified whole-engine improvement, retained as an isolated experiment. The active engine was not replaced.** Classical remains the default, including in the experimental executable.

The single branchless-input-preclip candidate improved 1,000,000-node throughput by **{primary['geomean_paired_speedup']:.3f}× (+{primary['gain_percent']:.1f}%)**, with a position-grouped hierarchical 95% bootstrap interval **{primary['hierarchical_grouped_bootstrap95'][0]:.3f}–{primary['hierarchical_grouped_bootstrap95'][1]:.3f}×**. This corresponds to approximately **{100*(1-1/primary['geomean_paired_speedup']):.1f}% less wall time** for identical fixed work, not 50% less time. At 1,000 ms, paired wall-NPS improved **{timed['geomean_paired_speedup']:.3f}× (+{timed['gain_percent']:.1f}%)**. All five control intervals exclude no gain; every position/control median is positive, with a minimum **{minimum:.3f}×**.

Head outputs passed **{head['head_bit_comparisons']:,} bitwise comparisons**, including signed-zero/extreme-finite/NaN cases. Both native transition oracles, original-model goldens, 147 existing targeted tests and all fixed-work search comparisons passed. **{preservation['checked_files']} protected files** remained unchanged.

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

* **{head['golden_fens']} existing golden FENs**, plus opening/middlegame/endgame fixtures and both turns.
* Deterministic legal walks with **{head['transitions']['moves']:,} moves**, **{head['transitions']['nulls']:,} null transitions**, captures, {head['transitions']['castling']} castlings, {head['transitions']['promotions']} promotions, {head['transitions']['ep']} en-passant moves and {head['transitions']['king']:,} king moves. Parent accumulators and boards are checked after sibling/null restoration.
* 20,000 seeded arbitrary finite accumulator patterns under both perspective orders, clipping boundaries, subnormals, maximum finite values and signed zeros.
* **{head['special_clip_lane_comparisons']:,} exact special-value clipping-lane comparisons**, including positive/negative infinity and quiet/signaling NaNs; **{head['nan_head_comparisons']} NaN head-output bit comparisons** also match. Finite head comparisons include exact White CP conversion. Non-finite head results are not sent to integer `lround`.
* Independent boundary assertions for the unchanged mate clamp and ties-away-from-zero rounding. Artificial CP boundary inputs test the conversion expression; they are not claimed reachable through this model's weights.

The existing native transition oracle passes independently in **both binaries**: **31,876 move transitions + 26,908 null transitions** per binary, bitwise exact. The original 32/16 model's **{len(r['legacy_model_golden_scores'])} golden scores** pass using existing immutable headers; explicitly selecting either `scalar` or `clip` produces identical native results. Those model-specific expected scores were not applied to 64/32. The 256 golden FENs are additional input positions for 64/32 parity.

Existing pytest checks: **147 passed, 13 deselected**, covering trained goldens, feature contract, incremental-versus-rebuild searches and terminal precedence on the isolated original-model compatibility build. Its default route remains scalar; the explicit `clip` CLI golden checks and the 64/32 native harness separately exercise the candidate. Five terminal/draw/mate fixtures pass with `clip`; classical fixed-node decisions match on all 12 fixtures with zero NNUE calls.

Preflight compares baseline, optimized, scalar fallback and the frozen tournament executable at depth 5 and 200,000 nodes: **24 four-build groups** match move, CP/mate score, PV, nodes, counters, depth and seldepth. Full performance runs add **168 paired fixed-node comparisons** at 200k/1M nodes, all exact. Legal moves/PVs are validated by the existing capture infrastructure.

Exact decision equivalence is a **fixed-work** claim. At fixed time, faster execution can complete deeper iterations and select a different move; this is not numerical drift. No GUI test or active-engine installation was performed.

## Compiler and generated machine code

Toolchain: Zig 0.13.0 / bundled Clang 18.1.6, Windows x64. Both builds use identical C++17 `-O2 -pthread -Wall -Wextra -ffp-contract=off` settings, compact accumulator strategy 2, no LTO, and the same copied weights. The assembly's embedded compiler record reports `x86-64` with effective host ISA features including AVX2. Merely looking at the CPU-name string would miss those enabled features.

| Property | Original | Experimental dispatcher |
|---|---:|---:|
| PDB function size | {fn['baseline']['function_bytes']:,} bytes | {fn['variant']['function_bytes']:,} bytes |
| Stack allocation in function prologue | {asm['baseline']['seh_stackalloc_bytes'][0]:,} bytes | {source['seh_stackalloc_bytes'][0]:,} bytes |
| Static vector input maximum instructions | 0 | {source['static_instructions']['vmaxps']} |
| Static vector input minimum instructions | 0 | {source['static_instructions']['vminps']} |
| FMA instructions | 0 | 0 |
| Annotated spills / reloads, complete dispatcher | 17 / 17 | 17 / 17 |

The optimized input block uses vector max/min and stores instead of per-input conditional branches; the dense loop still uses YMM multiply/add operations. The hidden/output clamp remains unchanged. The variant is inlined into `nnue_side_to_move`; it does not add a heap allocation. Existing accumulator storage is unchanged. The explicit 512-byte input buffer increases the function's measured stack allocation by only 112 bytes because stack-slot lifetimes overlap existing branches.

The dispatcher **grows** because it retains the complete original and integer fallback paths. Its total static branch count also grows; that is not the dynamic branch behavior of the selected optimized path. Spill annotations include other branches and callee-save handling and cannot establish hot-path spill cost. Full assembly/PDB and stripped instruction excerpts are retained. Cache misses, dynamic branch misses, retired instructions and cycles were not measured.

## Head microbenchmarks

Seven paired rotated-order passes; 10,000 warmup and 200,000 timed calls per batch. The same fixed-seed legal-walk frames are prepared before timing in both binaries. Checksums match across every paired batch. A volatile checksum and compiler fences consume outputs. The timer excludes startup, frame construction and weight refresh.

| Rotating frames | Original ns, median [IQR] | Optimized ns, median [IQR] | Median paired speedup |
|---|---:|---:|---:|
{chr(10).join(micro_rows)}

Speedups use paired same-pass ratios; they need not equal the ratio of the separately displayed latency medians. Each working set is one fixed corpus, not seven independent samples of chess positions. The 512 full frames occupy 602,112 bytes; working-set size changes both activation variation and locality. No cache-miss or branch-miss attribution is inferred from those sizes alone.

The separate 12-FEN repeated-root benchmark also has positive position medians throughout: the weakest median ratio is **{min(v['paired_speedup']['median'] for v in a['micro_fens']):.3f}×**. Its complete seven-pass per-FEN distributions are in `analysis.json`. Correctness probes include diverse finite activation patterns; no synthetic pattern is substituted for full-search performance acceptance.

## Full-search benchmarks and uncertainty

The frozen 12-position profiling suite, histories, production search options and 16 MiB hash are identical. One search thread, CPU0 affinity, no pondering, fresh search TT and one active engine search at a time. Seven paired rotated passes × 12 positions × five controls × two binaries = **840 searches**, with no extension based on results.

Primary statistic: compute the median paired wall-NPS ratio for each position, then the geometric mean across positions. For fixed-node searches that is equivalently the baseline/optimized wall-time ratio because exact node counts match. The hierarchical 95% bootstrap resamples positions, then paired repetitions within each sampled position, using 10,000 draws and seed 20261017. Repeats are not treated as independent chess positions. Intervals are descriptive for this selected fixed suite and observed conditions, not universal workload guarantees or strength confidence intervals.

| Control | Paired whole-search factor [grouped 95% interval] | Throughput gain | Cross-position median wall NPS, original / optimized, M/s | Median completed depth, original / optimized |
|---|---:|---:|---:|---:|
{chr(10).join(search_rows)}

NPS medians in the fourth column summarize different positions; dividing them is not the paired estimator. Raw records retain actual nodes, engine/wall elapsed time, reported/wall NPS, evaluation calls, quiescence nodes, all search counters and saved moves/scores/PVs. Fixed-node work is identical. Timed searches include unfinished iteration work while reporting the last completed decision.

### Per-position median paired throughput factors

| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1,000 ms |
|---|---:|---:|---:|---:|---:|
{chr(10).join(position_rows)}

No position/control median regressed. `search-per-position.csv` includes paired IQRs and all per-position performance/depth/call summaries. Median within-position repeat CVs (original / optimized) are **{cv}**. These are meaningful noise levels, but are much smaller than the approximately 47–58% grouped throughput gains.

Order sensitivity check, median pair factor with baseline-first / variant-first: **{orders}**. Both order subsets show a gain. Controls are related and intervals are not a multiple-comparison-adjusted family; the predeclared 1M-node result is the primary decision, with other controls corroborating it.

## Environmental controls and limitations

AC online before/after; the OEM Acer power scheme and last user-confirmed **Quiet/Eco** profile were not changed. The profile cannot be verified from the Windows power scheme alone. CPU: i5-13420H, 8 cores / 12 logical processors. Before/after aggregate frequency snapshots: {before['frequency_snapshot']['ProcessorFrequency']} / {after['frequency_snapshot']['ProcessorFrequency']} MHz, not measured search-core boost frequency. Temperature telemetry was unavailable; thermal stability cannot be claimed directly.

There were no concurrent agent-started CPU benchmarks. Other user/system activity was not stopped. Across 84 complete-position segments, estimated background CPU usage after subtracting benchmark processes had median **{load['median']:.2f}%**, IQR **{load['q1']:.2f}–{load['q3']:.2f}%**, range **{load['minimum']:.2f}–{load['maximum']:.2f}% of total logical capacity**. This does not reveal CPU0/sibling contention. Background activity and frequency variation limit precise clean-system forecasts. Paired rotation, broad position gains and effect size support the experimental acceptance despite that limitation; the report does not advertise a controlled idle-machine percentage.

## Remaining bottleneck

A bounded post-change own-child native sample repeats the established four-position method: 24 total 1.5-second searches, half sampled, after the performance schedule. It records **{n['samples']:,} valid instruction pointers**, with **{n['context_failures']} failed context/suspension attempts omitted**. Every successful suspension is paired with resumption; all searches finish. Median suspension/read interval is {n['suspension_ns']['median']/1000:.1f} μs, with a scheduling outlier up to {n['suspension_ns']['maximum']/1e6:.2f} ms. Sampled/unsampled per-position NPS ratios range {n['sampled_unsampled_nps_ratios']['minimum']:.3f}–{n['sampled_unsampled_nps_ratios']['maximum']:.3f}. This is a coarse hotspot estimate, not exact timing or hardware counters.

The optimized float head remains the largest named function at **{100*n['head_fraction']:.2f}%** of samples. Recognizable accumulator maintenance is approximately **{100*n['maintenance_fraction']:.2f}%**, with other work approximately **{100*n['other_fraction']:.2f}%**. Ordering/SEE are substantial secondary costs. These shares use a limited separate sample and should not be treated as a precise matched subtraction from the historical 52.90% profile. Debug line attribution maps much of the inlined new head to the dispatcher call site, so it does not separate remaining dense and hidden-clipping time.

The remaining head still performs the required dense arithmetic, hidden clipping and sequential output reduction. Accumulator bookkeeping now occupies a larger relative share. A separately approved Stage 2 maintenance experiment has a measurable target, but this stage does not change it.

## Acceptance and recommendation

**ACCEPTED as an isolated experimental implementation.** All numerical/transition/restoration gates pass; all fixed-work search results match; representative rotating-frame heads and full-search controls improve; every grouped lower interval exceeds one; no fixture median regresses. Only one proposed transformation was tested. No optimization variant was rejected or silently combined with another one.

Two harness/tooling details were corrected during verification: Python-chess can represent UCI `0000` as a falsey null Move rather than `None`, and cached Zig verbose invocations can emit no command trace. Neither correction changes a head, model or benchmark result. Local PDB lookup initially missed `engine.pdb` after the EXE was renamed for sampling; the correct filename was supplied and the **saved samples were resolved without rerunning searches**. Initial unresolved symbol output is retained for audit.

Keep the optimized binary and `clip` option isolated. **Do not replace the active engine or change the default evaluator without explicit promotion approval.** Accept this Stage 1 result; Stage 2 may follow independently after authorization. No Elo or tournament claim is made, and no games were run.

## Artifacts and reproduction

The workspace README gives exact PowerShell build, validation and bounded reproduction commands. `variant.patch`, `stage1_head.hpp` and harness scripts are committed. Raw evidence: `correctness.json`, `regressions.json`, `pytest.log`, `micro.json`, `search.json`, `analysis.json`, `search-per-position.csv`, `assembly-audit.json`, native samples/symbols and environment records. Ignored `artifacts/` retains baseline/optimized binaries, copied source/headers, PDB, full generated assembly and logs on the project drive.

`validation.json`, before/after protected hashes and `manifest.json` provide integrity receipts; text hashes include LF-normalized forms for Git line-ending conversion. The report is mirrored in the experiment directory. No training, new labels, quantization, search changes, sealed-test access, tournaments or active-engine promotion occurred.
'''
assert a['status']=='ACCEPTED'
(p.REPO/'NNUE_STAGE1_OPTIMIZATION_REPORT.md').write_text(report,encoding='utf-8')
(p.ROOT/'NNUE_STAGE1_OPTIMIZATION_REPORT.md').write_text(report,encoding='utf-8')
print('Rendered Stage 1 report:',len(report.split()),'words')
