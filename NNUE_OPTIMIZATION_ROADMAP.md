# StockBear NNUE 64/32 — Optimization Roadmap

Status: **proposal only; implementation requires explicit user approval**. The profiling phase changed no production source. `NNUE_PROFILING_REPORT.md` and `nnue-profiling-20261017/summary.json` supply the evidence.

## Shared contract and acceptance process

Freeze the current 64/32 checkpoint, export, evaluation mathematics, production search options and reference executable. Preserve classical as the default. Never touch training/sealed-test data or promote an evaluator as part of a speed experiment.

Each stage gets a separate commit, isolated binary and runtime/build switch that leaves the old path available. Accept one change at a time. Preserve White/Black unclipped accumulators, root refresh, child/sibling isolation, special moves, null history/cache isolation, mate clamp, CP rounding, completed iteration snapshots and every existing search-policy option.

Use the existing native transition oracle, golden score comparisons and fixed-node/depth search parity before speed measurements. Retain legal PVs, counters and input/history/settings in results. For a float optimization with no intended numerical change, require **bitwise head parity** on reachable frames, clipping-boundary/extreme finite patterns and both perspectives; then exact fixed-work move/score/PV/node/counter equivalence. A tolerance is not permission to change float semantics silently. Explicitly test signed zero and NaN operand behavior if an intrinsic changes clipping implementation, retaining a correct fallback where needed.

Benchmark serially under one user-confirmed power profile, plugged in. The current Quiet/Eco study had background-load and frequency uncertainty. Before accepting a small gain, use a quiet measurement window with recorded process-load deltas. Do not terminate user applications or alter power/antivirus settings automatically. Start with 7–10 rotated paired repeats; expand only when needed to resolve noise. Predefine a maximum run budget. Report per-FEN differences and intervals using positions as groups, avoiding pseudo-replication of repeated calls.

Primary speed gate: the lower bound of a position-grouped paired interval must exceed zero, the gain must exceed observed run noise, and no important fixture may regress materially without an explained tradeoff. Treat an approximately 3% threshold as an initial practical target, not a guaranteed detectable difference on this laptop. Use both 200,000-node and longer fixed-work searches, plus 100/500/1,000-ms validation. Do not accept on repeated-root microbenchmarks alone. No tournaments are authorized by this roadmap; any later strength validation needs its own approved bounded schedule.

## Stage 1 — Optimize the existing float head's clipping and control flow

**Priority: first.** Native samples place 52.90% in the head, including source locations for input clipping (15.98%) and dense work (27.32%). The existing head already emits YMM multiply/add instructions. Its identical production code takes approximately 121 ns on one repeated frame, 351 ns on 128 rotating frames and 496 ns on 512 frames. This is a locality/activation-variation sensitivity observation, not a measured branch-miss diagnosis.

**Likely files:** `engine/src/nnue.cpp`, optional private head helper/header, `nnue.hpp` only if selection requires it; `engine/tests/benchmark_nnue.cpp`; relevant golden/search tests; `tools/build_engine.py` only if build isolation needs support.

**Approach:** prototype one optional branchless input-transform/head variant. Explore a small preclipped 128-float buffer or explicitly controlled vector clipping while keeping the transposed weight layout. Retain the current 32 independent neuron sums and their original 128-addition order. Do not use FMA, fast-math, reassociation, output reduction reordering or zero skipping in this first change. Preserve the original kernel and use safe CPU dispatch/fallback. Inspect generated assembly to establish what actually changed.

**Expected benefit:** the largest measured target. A hypothetical 1.2–1.5× head improvement gives 1.10–1.21× whole search by Amdahl's law. Those are conditional scenarios; there is no measured improvement yet. Merely adding AVX2 flags is not a supported benefit.

**Correctness tests:** bitwise production-head comparison across fixed FENs, deterministic reachable accumulator walks, White/Black turn order, clipping boundaries, signed zeros, extreme unclipped sums and special-move frames. Run the 31,876-move / 26,908-null oracle, sibling restoration tests, mate-boundary/rounding tests and exact fixed-work search comparison. Test fallback dispatch without SIMD support.

**Performance tests:** frozen 12-position suite; varying 1/32/128/512-frame heads; low-overhead native samples; matched fixed-node latency and all three time budgets. Compare build byte/code changes and allocations. Keep microbench and whole-search outcomes separate.

**Accept/reject:** accept only if exact parity passes and a repeatable whole-search gain clears the shared gate. Reject if only one-frame head timings improve, frame locality worsens, or the gain disappears across search fixtures.

**Rollback:** select the original kernel or revert the focused commit; preserve all experimental binaries/results. Do not replace the active executable automatically.

## Stage 2 — Specialize accumulator bookkeeping and row updates

**Target:** approximately 12.74% identifiable sampled maintenance. Compact updates already cost a median 45.67 ns on repeated root/child fixtures and average 2.326 changed rows. Full refreshes are not the problem.

**Likely files:** `engine/src/nnue.cpp`, `nnue.hpp`, `diagnostics.hpp`; accumulator and search restoration tests. Avoid search algorithm changes.

**Approach:** inspect existing compact/small-state/fused-row prototypes before designing another strategy; none was enabled in profiling. Evaluate one small-state/changed-row specialization at a time, preserving sorted arithmetic order. Consider making search-only frame storage omit unused quantized/full-feature state, with a distinct type/contract rather than breaking generic APIs. Measure metadata copying and stack handling separately. Do not combine this with lazy materialization or a new head.

**Expected benefit:** modest. Halving the entire identifiable maintenance share would give only about **1.068×** whole-engine speed. Actual affected subsets are smaller. A smaller allocation is not automatically faster if it adds conversions or indexing.

**Correctness tests:** exact accumulator lane parity against production compact updates; all move types, rights loss, legal and pinned EP, promotions, castling, king moves, zero-delta null edges, maximum feature occupancy, child storage separation, search interruption and sibling restoration. Preserve null/TT draw context. Validate diagnostic byte/work counter definitions for changed frame types.

**Performance tests:** transition-class microbenchmarks, cold allocation/root setup, fixed-node release searches and whole-search sampling. Include EP-heavy and many-castling-rights fixtures; compare per-case regressions rather than only an average.

**Accept/reject:** require parity and a whole-search gain above noise. Reject a smaller/faster isolated frame if lookup/copy overhead erases its benefit.

**Rollback:** build-select original compact strategy 2 and retain the old public/generic frame path; revert one specialization commit.

## Stage 3 — Decide whether deferred materialization is worthwhile

**Target:** eager updates that can actually be avoided. Although 15.64% of frames are directly unused, only **2.65%** have no evaluated descendant. The mean pending chain is 2.462 edges; direct non-evaluation is not proof that a delta can be discarded.

**Likely files:** `engine/src/search.cpp` accumulator plumbing only; `nnue.cpp`, `nnue.hpp`, `diagnostics.hpp`; native transition and search equivalence tests.

**Approach:** audit the existing inactive deferred prototype first. Instrument materializations, edge traversal, row replay, zero-state null handling and exception/interrupt restoration. Never change pruning, TT rules or evaluation-request locations. Keep branch-local chains and exact row sequences; do not cancel/reorder float additions without proof of bitwise equivalence.

**Expected benefit:** small/unknown; simple uniform-cost removal of leaf-unused updates affects only about 0.34% of whole sampled time. This does not support an elaborate lazy rewrite as the first optimization.

**Correctness tests:** deep unevaluated chains, PVS/aspiration retries, LMR verification, siblings at reused ply, null subtrees, TT exits, interrupted searches and king/EP/rights transitions. Require all original exact fixed-work decisions/counters.

**Performance tests:** count actual update/row reductions and added bookkeeping; fixed-node release timing on both this fixture suite and deliberately high-cutoff legal fixtures. Avoid judging from a constructed best case alone.

**Accept/reject:** reject if saved arithmetic fails to exceed stack/chain overhead or if measured gain cannot clear noise. Retain eager production mode as the default.

**Rollback:** disable the deferred build/runtime switch; revert plumbing-only commits independently of earlier head improvements.

## Stage 4 — Measure search activation sparsity, then assess sparse float work

**Target:** potentially unnecessary dense arithmetic. Fixture roots have a median **75/128 zero inputs**, but this is not a search-wide activation distribution.

**Likely files:** an isolated instrumentation copy first; later `engine/src/nnue.cpp`, benchmark harness and tests if justified.

**Approach:** after approval, sample clipped-input nonzero histograms by search phase/ply without collecting training data. Account for nonzero-index creation, extra branches and weight access. Only prototype sparse dispatch if expected saved work exceeds measured selection overhead. Keep dense fallback and exact addition order; signed-zero and zero-multiply semantics need explicit treatment.

**Expected benefit:** unknown. Current root sparsity cannot establish whole-search speedup.

**Correctness tests:** all-dense, all-zero, boundary, signed-zero and randomized finite inputs; bitwise head parity, transition parity and exact fixed-node search behavior.

**Performance tests:** real search sparsity distributions and dense/sparse crossover measurements, followed by the standard release suite. Reject micro-only gains or unstable crossover regressions.

**Rollback:** retain/select dense head; remove sparse dispatch in a focused commit without touching the model.

## Stage 5 — Gate a separate integer SIMD feasibility experiment

**Target:** the head remains substantial after accepted float changes. Existing int16 inference was historically **2.74× slower** and already contains compiler-generated XMM multiply-add operations; SIMD absence alone is not the explanation.

**Likely files:** isolated inference/export experiment first; potentially `nnue.cpp`, generated-weight support, format/export helpers, benchmark and parity tests. Keep all existing exports/checkpoints immutable.

**Approach:** separately price input conversion, packing, row-major reductions and generic integer-update fallback. Investigate an int16 AVX2 neuron/layout strategy before a different byte representation. CPU AVX-VNNI support is available but does not establish an appropriate scale or accuracy contract. Any new representation requires explicit subsequent approval, its own identifier and documented numerical semantics; no retraining or active-model replacement is implied.

**Expected benefit:** unknown. Halving bytes or selecting an intrinsic does not guarantee fewer instructions. Compare against the best accepted float implementation, not an obsolete slow baseline.

**Correctness tests:** formal accumulator/dot-product overflow bounds; clipping and rounding boundaries; frozen non-test validation/golden positions; score-error distributions, mate clamp and legal search behavior. Quantization normally changes scores, so it cannot silently pass under a float “exact parity” claim. A future separately approved paired-game study would be necessary before deployment.

**Performance tests:** existing and proposed integer stages, conversion-inclusive head, actual incremental search updater and whole-search timing. Keep generated artifacts separate and report all conversion/layout overhead.

**Accept/reject:** reject immediately if integer is not reproducibly faster end to end. Even a speed win does not permit promotion without approved numerical/strength gates.

**Rollback:** select float; preserve and retain the original immutable checkpoint/export. Experimental integer artifacts must never overwrite them.

## Work currently not justified

King-relative accumulator caches and refresh accelerators have essentially no measured target in this king-independent v2 workload. Generic allocator replacement, global alignment changes and GPU inference are not supported by this profile. Search/pruning retuning, network architecture changes and retraining are outside this plan.

**Next action:** request approval for Stage 1 only, with the frozen baseline and switches above. Until that approval, preserve the current engine unchanged.
