# StockBear — Stage 3 dense float32 inference optimization report

## Executive decision

**INCONCLUSIVE.** Retained experimental choice: **Stage 1**.
Two profile-directed changes were tested independently: controlled dense-loop
unrolling and vector hidden clipping. Neither includes Stage 2/2.1 sorting,
fusion, state-layout changes, altered weights or search policy.
The active engine and classical default remain unchanged. Any accepted candidate
is an isolated research binary and requires separate approval for production.

No training, labeling, sealed-test access, tournaments, quantization, lazy updates,
GPU work, power changes or subsequent optimization stage took place. There were
no routine intermediate commits; the completed study is published together.

| Variant | 1M factor | 1M grouped 95% | 1000-ms factor | 1000-ms grouped 95% | 128-frame head factor | Status |
|---|---|---|---|---|---|---|
| hiddenclip | 1.0642× | [1.0399, 1.0848] | 1.0768× | [1.0512, 1.1019] | 1.1146× | INCONCLUSIVE |
| unroll4 | 0.9834× | [0.9651, 1.0147] | 0.9965× | [0.9607, 1.0178] | 1.0637× | INCONCLUSIVE |

## Exact baseline, model and environment

Branch `codex/nnue-stage3-dense-head` starts from accepted Stage 1
`f397a5af002900bbc15a7261dc6027c48daaeff4`. Baseline is the exact copied `clip` executable,
SHA-256 `e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d`. Original native transition and
161,420-comparison head tests were reconfirmed before any candidate.

Model: existing 780-feature, dual-64 accumulator, 32-hidden-neuron, scalar-output
NNUE, documented 54,209 parameters. Checkpoint SHA-256
`7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`;
export SHA-256 `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`. Neither was regenerated or modified.
Both perspectives, transformed weights and 400× score scale remain unchanged.

The exact Stage 1 compiler command is reused: Zig 0.13 / Clang 18.1.6, C++17,
`-O2 -pthread -Wall -Wextra -ffp-contract=off`, compact update strategy 2.
No fast-math, reassociation, FMA contraction, new ISA flag or LTO was added.
Generated CodeView CPU/feature lists match across builds; actual linked code
already contains YMM arithmetic, so enabling AVX2 was not an optimization.

All search comparisons use one thread, CPU0, 16 MiB hash, no pondering, fresh TT,
the frozen 12 FENs/full histories, identical search options and per-binary `clip`.
Baseline/candidate selection is by separate executable, not a changed UCI default.
AC is recorded before/after, OEM Acer plan and last-confirmed Quiet/Eco retained.
Current NitroSense mode and temperature/throttling are not independently exposed
by those Windows settings. Other apps were not closed. CPU-intensive experiments
ran serially; process-load deltas are recorded separately for each trial.

## Fresh baseline and profiling method

Before candidate selection: three fresh baseline passes at 200k/1M nodes and
100/500/1000 ms (**180 searches**) plus three passes of head microbenchmarks at
1/32/128/512 frames. Those exploratory baseline timings are not pooled into later
paired comparisons. Fresh controls are interleaved again with every candidate.

| Head frames | Fresh baseline median ns |
|---|---|
| 1 | 112.15 |
| 32 | 128.30 |
| 128 | 130.06 |
| 512 | 140.38 |

Native sampling uses only our copied baseline child, CPU0 search and CPU2
sampler, with randomized 2–4 ms spacing. Four representative positions × three
rotated sampled/unsampled pairs at 1500 ms give 24 searches. Each successful
SuspendThread is paired with ResumeThread in `finally`. The exact EXE and matching
local PDB are preserved; the existing sampler is reused without rewriting prior
studies. No driver or machine-wide profiler was installed.

There are **3,926 valid instruction pointers** and
2 failed attempts, which are excluded. Median suspension/read
interval is 40.55 μs. Paired sampled/unsampled
NPS ratio median is 0.9960, range
0.9284–1.0288.
This supports coarse hotspot localization, not exact cycles or stall attribution.

The installed MinGW objdump cannot read this x64 PE. Pinned Capstone 5.0.3 was
added to the project environment for actual linked disassembly. A local PDB gives
the head's RVA/size; PE sections map its bytes to disk, and decoding accounts for
every byte. Sample addresses are normalized by the runtime image base. Selected
`CLIP` dispatch and loop-backedge addresses define regions; retained inactive
reference/scalar/integer paths are excluded from active-region attribution.

| Sample region | Samples | All-sample share | Head-sample share |
|---|---|---|---|
| dense_loop | 859 | 21.88% | 68.34% |
| head_other | 31 | 0.79% | 2.47% |
| hidden_clip_and_output | 325 | 8.28% | 25.86% |
| input_clip_and_bias | 42 | 1.07% | 3.34% |
| outside_head | 2,669 | 67.98% | — |

**Largest remaining head cost: dense hidden-layer work.** The four-vector
dense loop dominates samples. Hidden clipping/output is the second addressable
region; input clipping/bias preparation is already a small sampled cost. No
new input-buffer rewrite was justified. Sampling cannot isolate branch misses,
cache misses, port pressure or exact dependency stalls. Debug/inlining and
suspension bias remain; region shares are approximate.

## Dense-head machine code and opportunities

Baseline input clipping performs 16 operand-ordered vector max/min groups and
stores 128 clipped floats. Biases initialize 32 hidden values. The dense loop
loads/broadcasts one input, loads four contiguous 8-float weight groups and updates
four independent YMM accumulators. Each neuron still has its required 128-term
ordered chain; interleaving neurons is allowed, reassociating a neuron's terms is
not. There is no per-iteration hidden spill/store in the baseline loop; its stack
references are input broadcasts. Baseline already has useful SIMD, transposed
weight locality and register-resident hidden chains.

The dense loop has 128 trips, four multiply/add pairs and four loop-control
instructions per trip. Controlled unrolling tests instruction scheduling and
control amortization without changing the reduction tree. The scalar output path
clips hidden values through comparisons/branches before the sequential 32-term
output reduction. Applying the proven operand-ordered clamp to hidden vectors
tests that second opportunity without changing the sum or input clipping.

| Build | Linked head bytes | Decoded instructions | Stack bytes | Spill annotations | Reload annotations | Saved XMM slots | Static branches |
|---|---|---|---|---|---|---|---|
| baseline | 3527 | 664 | [1120] | 17 | 17 | 10 | 47 |
| unroll4 | 3703 | 692 | [1056] | 17 | 17 | 10 | 47 |
| hiddenclip | 3927 | 732 | [1120] | 17 | 17 | 10 | 41 |

| Selected CLIP build | Dense body bytes | Body instructions | Vector multiplies | Vector adds | Broadcasts | Output conditional branch sites |
|---|---|---|---|---|---|---|
| baseline | 59 | 13 | 4 | 4 | 1 | 5 |
| hiddenclip | 59 | 13 | 4 | 4 | 1 | 0 |
| unroll4 | 227 | 40 | 16 | 16 | 4 | 5 |

Dense counts are static per emitted loop body, not total dynamic operations.
`kernel-shapes.json` retains register names, loop controls and stack operands.
Whole-head counts include preserved fallback/integer paths; spill annotations and
ten saved XMM slots must not be described as ten active dense spills. The dispatcher
still contains the inlined selected head and unchanged fallback code. Candidate
function size/register changes are tradeoffs, not proof of cache/stall causes.
No inspected float-head machine code contains FMA instructions.

## Independent candidates

* **unroll4:** one `#pragma clang loop unroll_count(4)` on the existing 128-input
  dense loop. Same j order, multiplications/additions, weights, biases, input
  clipping, hidden clipping and output order. No handwritten SIMD is added.
* **hiddenclip:** use the existing `clip_inputs` helper in place on the 32 hidden
  values after the unchanged dense loop, then run the original ordered output
  multiplication/addition sequence. The operand order preserves the clamp's
  signed-zero/NaN behavior. Input clipping is unchanged; AVX/OS-state guard and
  original scalar fallback remain intact.

Both source headers are independently copied from Stage 1. Focused patches show
the complete change; no combination or third variant was tried. SHA-256 source
identities and profile-based selection were frozen before performance results.

## Bitwise, transition and search correctness

| Candidate | Original head bit checks | Extra Stage 1 special heads | Legal/null transitions |
|---|---|---|---|
| hiddenclip | 161,420 | 4,352 | 31,876 / 26,908 |
| unroll4 | 161,420 | 4,352 | 31,876 / 26,908 |

The original suite includes 256 golden FENs, both perspectives, deep legal
walks, special moves, 20,000 arbitrary finite patterns on both turns, clipping
boundaries, ±0, subnormals/extreme finite values, infinities, quiet/signaling NaNs,
1,920 special clipping lanes, CP rounding and mate clamping. Additional 4,352
heads place special values in every one of 128 lanes on both turns, including
mixed distinct NaN payloads; exact production Stage 1 output bits are frozen
and compared directly. Non-finite head values never enter integer conversion.

The 31,876 legal / 26,908 null oracle checks accumulator lanes, parent/sibling
isolation, roots, promotions, castling, EP and null/deep-walk restoration. All
accumulator source is byte-identical to Stage 1. For each correct candidate,
36 depth-5/200k/1M comparisons match best move, score, PV, nodes, completed depth,
seldepth, evaluation/qnode counts and every reported counter. Repeated fixed-node
performance blocks also match, including completed iteration snapshots after
excluding elapsed time/NPS. Timed decisions are not required to match because
more work may complete before the deadline.

Each correct variant passes 24 explicit UCI cancellation checks and 12 following
fixed-node reruns, terminal/draw precedence, scalar fallback with SIMD disabled,
and 12 unchanged classical searches. Separate correctness-only observers assert
internal board/history and root accumulator bits after return/interruption;
their regressions pass and are not used for timing. No full GUI/desktop regression
claim is made for this isolated source-copy investigation.

## Representative inference microbenchmarks

Seven rotated pairs per variant; identical seeded legal-walk corpora and 1,176-byte
frame layout, 1/32/128/512 frames, 10,000 warmups and 200,000 timed calls per batch.
Volatile output checksums and compiler fences consume every production-head result.
Checksums match within every pair. The timer excludes frame creation/root refresh.
Reported ns includes common indexing, external-call and checksum overhead; no
subtraction is used to manufacture an isolated arithmetic latency.
Median paired factors need not equal ratios of separately displayed medians.
Repeat-only intervals describe timing variation of a fixed corpus, not independent
chess positions. Different working sets vary locality and activation patterns;
no cache-miss cause is inferred. No separate dense-only kernel with a different
function/register boundary is used as an acceptance proxy; native selected-loop
localization and complete production-head timings remain the measured evidence.

### hiddenclip

| Frames | Stage 1 ns [IQR] | Candidate ns [IQR] | Paired factor | Repeat-only 95% |
|---|---|---|---|---|
| 1 | 118.27 [116.17, 126.46] | 108.51 [107.48, 122.03] | 1.0900× | [0.9938, 1.1274] |
| 32 | 131.30 [126.00, 141.23] | 114.77 [113.83, 119.56] | 1.0986× | [1.0672, 1.1991] |
| 128 | 139.28 [133.87, 140.04] | 123.73 [115.33, 132.64] | 1.1146× | [1.0683, 1.1969] |
| 512 | 144.05 [138.84, 150.44] | 117.16 [116.87, 119.95] | 1.1819× | [1.1680, 1.3249] |

### unroll4

| Frames | Stage 1 ns [IQR] | Candidate ns [IQR] | Paired factor | Repeat-only 95% |
|---|---|---|---|---|
| 1 | 116.34 [113.25, 116.77] | 110.90 [110.08, 113.45] | 1.0258× | [0.9969, 1.0595] |
| 32 | 127.83 [124.88, 131.74] | 118.69 [116.86, 120.19] | 1.0647× | [1.0594, 1.1512] |
| 128 | 129.46 [125.34, 144.13] | 119.42 [119.01, 119.97] | 1.0637× | [1.0340, 1.2543] |
| 512 | 138.53 [133.83, 142.48] | 123.94 [122.50, 129.22] | 1.1069× | [1.0417, 1.1384] |

## Whole-engine throughput

Seven paired rotated passes initially, fresh matched controls for each candidate.
Every correct candidate has 840 primary searches (12 × five controls × two
builds × seven passes). There are no tournaments. A maximum-ten extension requires
a positive micro/fixed-work signal with uncertain grouped bounds and no material
fixture/order failure, a written justification, and the 45-minute primary budget.
No result-driven variant tuning is permitted.

Statistic: `exp(mean(per-position median(log(paired wall-NPS ratio))))`, equal
weight per fixture. For fixed nodes this is inverse paired wall-time. Grouped
95% bootstrap resamples positions, then paired repetitions within position;
10,000 draws, seed 20261017. Repeated runs are not independent positions.
Intervals do not remove load/frequency drift, model temporal autocorrelation,
adjust all comparisons as a family, or measure Elo. Order subsets are sensitivity
checks. The raw files retain wall NPS/time, actual nodes, completed depth/seldepth,
evaluations, qnodes, decisions/PVs and all counters/iteration snapshots.

### hiddenclip

| Control | Paired factor | Grouped 95% | Position range | Baseline-first / candidate-first medians |
|---|---|---|---|---|
| 200,000 nodes | 1.0530× | [1.0232, 1.0763] | [1.0015, 1.0937] | 1.0741× / 1.0472× |
| 1,000,000 nodes | 1.0642× | [1.0399, 1.0848] | [0.9994, 1.1110] | 1.0428× / 1.0831× |
| 100 ms | 1.0566× | [1.0160, 1.1110] | [0.9300, 1.1556] | 1.0325× / 1.0881× |
| 500 ms | 1.0632× | [1.0381, 1.0845] | [1.0407, 1.0901] | 1.0524× / 1.0674× |
| 1,000 ms | 1.0768× | [1.0512, 1.1019] | [1.0443, 1.1265] | 1.0332× / 1.1137× |

Runtime 7.9 minutes; 840 primary searches. Background load median 14.56%, range 9.73–34.20% of total logical capacity after subtracting benchmark processes; not CPU0 contention or thermal telemetry.

| Fixture | 200k | 1M | 100 ms | 500 ms | 1000 ms |
|---|---|---|---|---|---|
| opening | 1.0937× | 1.0343× | 1.1005× | 1.0429× | 1.0622× |
| quiet_middlegame | 1.0752× | 1.0881× | 1.0821× | 1.0407× | 1.0485× |
| tactical | 1.0749× | 1.1110× | 1.0721× | 1.0663× | 1.1008× |
| pawn_endgame | 1.0155× | 0.9994× | 1.0762× | 1.0851× | 1.0823× |
| piece_endgame | 1.0448× | 1.0712× | 0.9300× | 1.0532× | 1.0626× |
| imbalance | 1.0890× | 1.0831× | 1.1180× | 1.0854× | 1.0877× |
| castling_rights | 1.0539× | 1.0813× | 0.9847× | 1.0411× | 1.1009× |
| promotion | 1.0501× | 1.0780× | 1.0883× | 1.0660× | 1.0443× |
| en_passant | 1.0264× | 1.0225× | 1.0330× | 1.0542× | 1.1265× |
| pins | 1.0764× | 1.1046× | 1.0363× | 1.0901× | 1.0520× |
| attack_complex | 1.0015× | 1.0586× | 1.1556× | 1.0737× | 1.1077× |
| opening_history | 1.0392× | 1.0441× | 1.0225× | 1.0609× | 1.0507× |

Material fixture/control medians (>3% elapsed): **1**.

| Fixture | Control | Factor | Elapsed regression |
|---|---|---|---|
| piece_endgame | 100 ms | 0.9300× | 7.53% |

### unroll4

| Control | Paired factor | Grouped 95% | Position range | Baseline-first / candidate-first medians |
|---|---|---|---|---|
| 200,000 nodes | 0.9923× | [0.9600, 1.0134] | [0.9681, 1.0354] | 0.9859× / 0.9928× |
| 1,000,000 nodes | 0.9834× | [0.9651, 1.0147] | [0.9593, 1.0231] | 0.9584× / 1.0230× |
| 100 ms | 0.9788× | [0.9433, 1.0113] | [0.9084, 1.0441] | 0.9926× / 0.9625× |
| 500 ms | 0.9860× | [0.9628, 1.0189] | [0.9510, 1.0281] | 0.9557× / 1.0177× |
| 1,000 ms | 0.9965× | [0.9607, 1.0178] | [0.9555, 1.0578] | 0.9373× / 1.0377× |

Runtime 8.1 minutes; 840 primary searches. Background load median 15.85%, range 10.74–32.37% of total logical capacity after subtracting benchmark processes; not CPU0 contention or thermal telemetry.

| Fixture | 200k | 1M | 100 ms | 500 ms | 1000 ms |
|---|---|---|---|---|---|
| opening | 0.9754× | 0.9797× | 1.0272× | 1.0281× | 1.0316× |
| quiet_middlegame | 0.9939× | 0.9873× | 1.0096× | 0.9895× | 0.9581× |
| tactical | 0.9884× | 1.0068× | 0.9527× | 0.9667× | 1.0338× |
| pawn_endgame | 1.0100× | 0.9769× | 0.9542× | 0.9569× | 1.0578× |
| piece_endgame | 0.9694× | 0.9612× | 0.9236× | 0.9510× | 0.9761× |
| imbalance | 0.9823× | 0.9593× | 1.0441× | 1.0170× | 1.0044× |
| castling_rights | 0.9681× | 0.9976× | 0.9084× | 0.9951× | 0.9670× |
| promotion | 0.9812× | 0.9689× | 0.9975× | 0.9782× | 0.9555× |
| en_passant | 1.0090× | 1.0231× | 1.0016× | 0.9819× | 1.0028× |
| pins | 1.0103× | 0.9864× | 1.0430× | 1.0007× | 0.9626× |
| attack_complex | 0.9863× | 0.9753× | 0.9154× | 0.9864× | 1.0212× |
| opening_history | 1.0354× | 0.9801× | 0.9809× | 0.9837× | 0.9934× |

Material fixture/control medians (>3% elapsed): **17**.

| Fixture | Control | Factor | Elapsed regression |
|---|---|---|---|
| piece_endgame | 200,000 nodes | 0.9694× | 3.16% |
| castling_rights | 200,000 nodes | 0.9681× | 3.29% |
| piece_endgame | 1,000,000 nodes | 0.9612× | 4.04% |
| imbalance | 1,000,000 nodes | 0.9593× | 4.25% |
| promotion | 1,000,000 nodes | 0.9689× | 3.21% |
| tactical | 100 ms | 0.9527× | 4.96% |
| pawn_endgame | 100 ms | 0.9542× | 4.80% |
| piece_endgame | 100 ms | 0.9236× | 8.27% |
| castling_rights | 100 ms | 0.9084× | 10.08% |
| attack_complex | 100 ms | 0.9154× | 9.24% |
| tactical | 500 ms | 0.9667× | 3.44% |
| pawn_endgame | 500 ms | 0.9569× | 4.51% |
| piece_endgame | 500 ms | 0.9510× | 5.16% |
| quiet_middlegame | 1,000 ms | 0.9581× | 4.38% |
| castling_rights | 1,000 ms | 0.9670× | 3.42% |
| promotion | 1,000 ms | 0.9555× | 4.66% |
| pins | 1,000 ms | 0.9626× | 3.88% |

### Hidden-clipping endgame anomaly: saved-record audit

| Pass | Order | Factor | Baseline / candidate nodes | Baseline / candidate depth | Wall seconds, baseline / candidate |
|---|---|---|---|---|---|
| 1 | hiddenclip / baseline | 0.9285× | 236,800 / 220,928 | 6 / 6 | 0.102503 / 0.102998 |
| 2 | baseline / hiddenclip | 0.9132× | 225,024 / 206,592 | 6 / 6 | 0.102482 / 0.103025 |
| 3 | hiddenclip / baseline | 1.0613× | 202,240 / 213,760 | 6 / 6 | 0.103086 / 0.102665 |
| 4 | baseline / hiddenclip | 1.0490× | 248,320 / 259,584 | 6 / 7 | 0.102577 / 0.102225 |
| 5 | hiddenclip / baseline | 1.1960× | 242,944 / 291,072 | 6 / 7 | 0.102261 / 0.102440 |
| 6 | baseline / hiddenclip | 0.9300× | 276,992 / 257,536 | 7 / 6 | 0.102378 / 0.102353 |
| 7 | hiddenclip / baseline | 0.9050× | 274,688 / 251,392 | 7 / 6 | 0.102025 / 0.103169 |

The 100-ms piece-endgame median factor is 0.9300×;
repeat-only bootstrap interval [0.9132, 1.0613] crosses one.
There are 3 winning and 4
losing pairs. Engine-reported times are exactly 100 ms and protocol wall overhead
is small, so a large protocol delay does not explain the loss. Rates vary and
some searches cross a completed-depth boundary. Order medians are
0.9300× baseline-first /
0.9949× candidate-first; segment-load
correlation is -0.372, only an observational
association. This does not prove a repeatable kernel defect or establish a
specific scheduling, frequency, cache or branch cause.

No pair was removed, relabeled or replayed. The material median remains
unexplained, so the candidate is not accepted despite positive aggregate bounds.
The predeclared extension rule excludes material fixture/order failures; neither
trial was extended beyond seven passes. This audit ran **zero new searches**.
The promising implementation is preserved without weakening its acceptance gate.

Complete per-position CSV includes median NPS/time, nodes, depths, evaluation
calls and qnodes. JSON also retains paired quartiles and within-position repeat CV.
Absolute NPS from sequential variant trials is not treated as a matched comparison
between those candidates. No unverified combined speedup is calculated.

## Acceptance, classical context and remaining work

| Candidate | Decision | Micro support | Search intervals | Order support | No material fixture loss |
|---|---|---|---|---|---|
| hiddenclip | INCONCLUSIVE | True | True | True | False |
| unroll4 | INCONCLUSIVE | True | False | False | False |

Acceptance requires every numerical/search gate, faster representative rotating
heads with no material common-head loss, positive grouped support across search
controls/orders, and no unexplained >3% fixture median elapsed regression. Three
percent is a practical target, not a mandatory minimum gain. Micro-only gains or
one positive timed control cannot justify acceptance.

Optional fresh classical comparison was **not run** because no candidate passed the primary gates. No old scalar/Classical ratio is projected into a claimed new recovery or Elo result.

Fresh sampled head fraction is approximately 32.02%.
If that fraction were representative and other costs fixed, a hypothetical 1.5×
head speedup would imply `1 / ((1-f) + f/1.5)` =
1.119× whole speed. This is an Amdahl planning
estimate, not a measured result or a promise; actual matched search tables take
precedence. The dense arithmetic remains required under this bitwise contract.

## Final answers

1. **Largest head cost:** dense hidden-layer math, with 859
   samples versus 325 in hidden clipping/output.
2. **Compiler strengths:** four independent YMM neuron groups, contiguous
   transposed weights, register-resident hidden chains and effective input clipping.
3. **Attempted changes:** independent four-way loop unrolling and vector hidden
   clipping using the already verified helper. No alternative reduction tree.
4. **Head latency:** the four working-set tables above give the actual paired
   effects and variation; faster arithmetic alone is not accepted as a search gain.
5. **Whole engine:** use each candidate's five matched controls and per-position
   failures. Overall decision: **INCONCLUSIVE**.
6. **Exact Stage 1-relative speedups:** all five point estimates and grouped
   intervals are tabulated; no original-scalar comparison substitutes for Stage 1.
7. **Evaluation bits:** accepted/performance-tested candidates pass the original
   suite plus 4,352 frozen mixed-special-value production outputs. Any rejected
   numerical candidate is explicitly identified before timing.
8. **Fixed work:** all performance-tested moves, scores, PVs, nodes, completed
   depths, evaluations, qnodes and counters/iteration snapshots are identical.
9. **Fixture regressions:** every material median is listed; none is hidden by
   an aggregate. Timed-search decisions may differ with completed work.
10. **Decision:** **INCONCLUSIVE**; experimental retained choice
    **Stage 1**. The production default remains classical.
11. **Classical proximity:** only the fresh optional comparison above, if run,
    supports a current ratio. No throughput-to-Elo conversion is made.
12. **Next:** first resolve the frozen hidden-clipping candidate's 100-ms endgame
    anomaly under a separately authorized, quieter matched measurement with
    per-search CPU-time/frequency evidence. Then obtain hardware-counter evidence
    for dense-loop dependency/load balance before a more complex scheduling kernel.
    The retained fallback dispatcher also has common save/restore costs, but
    its whole-head annotations alone do not establish a worthwhile split kernel.
    No new stage or unverified combination began here.

## Preservation and artifacts

**829/829 protected files unchanged.**
Original engines/weights, previous studies and selected checkpoint/export remain
preserved. The Stage 2/2.1 tracked reports stay on their original commits because
this branch starts from Stage 1; references are archived locally. Sealed data was
not enumerated/read. Production source/defaults and search policy are unchanged.

The workspace README gives reproduction/resume commands. Committed artifacts
include focused headers/patches, raw JSON/CSV, exact build/correctness receipts,
native samples/symbols, real linked disassembly and compiler assembly excerpts.
Original/candidate EXE/PDB, complete source copies/generated headers/assembly and
compiler caches stay under ignored `artifacts/` on Z:. The manifest records raw
and LF-normalized hashes, and the report is mirrored in the workspace. No GUI
verification is claimed. The bounded experiment ends here.
