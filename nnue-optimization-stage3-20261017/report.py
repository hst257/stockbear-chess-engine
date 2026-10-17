"""Generate the final dense-head report from frozen receipts; no engine work."""
import statistics as s
import experiment as p

a=p.common.load(p.ROOT/'analysis.json');prof=p.common.load(p.ROOT/'profile-analysis.json')
plan=p.common.load(p.ROOT/'plan.json');shapes=p.common.load(p.ROOT/'kernel-shapes.json')
initial=p.common.load(p.ROOT/'initial-baseline.json')
preserved=p.common.load(p.ROOT/'preservation-after.json')
context=p.common.load(p.ROOT/'classical-context.json')
diagnosis=p.common.load(p.ROOT/'regression-diagnosis.json')
head_samples=sum(v for k,v in prof['counts'].items() if k!='outside_head')
head_share=head_samples/prof['valid_samples']


def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+ '|'.join(['---']*len(headers))+'|\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)+'\n'


def factor(v):return f'{v:.4f}×'
def ci(v):return f'[{v[0]:.4f}, {v[1]:.4f}]'
def control(r):return f"{r['budget']:,} {'nodes' if r['mode']=='nodes' else 'ms'}"


text=f'''# StockBear — Stage 3 dense float32 inference optimization report

## Executive decision

**{a['decision']}.** Retained experimental choice: **{a['retained_baseline']}**.
Two profile-directed changes were tested independently: controlled dense-loop
unrolling and vector hidden clipping. Neither includes Stage 2/2.1 sorting,
fusion, state-layout changes, altered weights or search policy.
The active engine and classical default remain unchanged. Any accepted candidate
is an isolated research binary and requires separate approval for production.

No training, labeling, sealed-test access, tournaments, quantization, lazy updates,
GPU work, power changes or subsequent optimization stage took place. There were
no routine intermediate commits; the completed study is published together.

## Exact baseline, model and environment

Branch `codex/nnue-stage3-dense-head` starts from accepted Stage 1
`{plan['baseline_commit']}`. Baseline is the exact copied `clip` executable,
SHA-256 `{plan['baseline_binary_sha256']}`. Original native transition and
161,420-comparison head tests were reconfirmed before any candidate.

Model: existing 780-feature, dual-64 accumulator, 32-hidden-neuron, scalar-output
NNUE, documented 54,209 parameters. Checkpoint SHA-256
`7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`;
export SHA-256 `{plan['network_sha256']}`. Neither was regenerated or modified.
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

'''
text+=table(['Head frames','Fresh baseline median ns'],[[size,f"{s.median(r['ns'] for r in initial['micro_records'] if r['frames']==size):.2f}"] for size in [1,32,128,512]])
text+='''Native sampling uses only our copied baseline child, CPU0 search and CPU2
sampler, with randomized 2–4 ms spacing. Four representative positions × three
rotated sampled/unsampled pairs at 1500 ms give 24 searches. Each successful
SuspendThread is paired with ResumeThread in `finally`. The exact EXE and matching
local PDB are preserved; the existing sampler is reused without rewriting prior
studies. No driver or machine-wide profiler was installed.

'''
text+=f'''There are **{prof['valid_samples']:,} valid instruction pointers** and
{prof['failed_samples']} failed attempts, which are excluded. Median suspension/read
interval is {prof['suspension_ns_median']/1000:.2f} μs. Paired sampled/unsampled
NPS ratio median is {prof['sampling_speed_ratio']['median']:.4f}, range
{prof['sampling_speed_ratio']['minimum']:.4f}–{prof['sampling_speed_ratio']['maximum']:.4f}.
This supports coarse hotspot localization, not exact cycles or stall attribution.

The installed MinGW objdump cannot read this x64 PE. Pinned Capstone 5.0.3 was
added to the project environment for actual linked disassembly. A local PDB gives
the head's RVA/size; PE sections map its bytes to disk, and decoding accounts for
every byte. Sample addresses are normalized by the runtime image base. Selected
`CLIP` dispatch and loop-backedge addresses define regions; retained inactive
reference/scalar/integer paths are excluded from active-region attribution.

'''
text+=table(['Sample region','Samples','All-sample share','Head-sample share'],[
    [name,f'{count:,}',f"{100*count/prof['valid_samples']:.2f}%",f"{100*count/head_samples:.2f}%" if name!='outside_head' else '—']
    for name,count in prof['counts'].items()])
text+='''**Largest remaining head cost: dense hidden-layer work.** The four-vector
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

'''
rows=[]
for label in ['baseline','unroll4','hiddenclip']:
    path=p.ROOT/('head-inspection-'+label+'.json')
    if not path.exists():continue
    item=p.common.load(path)
    rows.append([label,item['head_bytes'],len(item['instructions']),item['assembly']['stack_bytes'],
        item['assembly']['spills'],item['assembly']['reloads'],item['assembly']['callee_saved_xmm_slots'],item['static_branches']])
text+=table(['Build','Linked head bytes','Decoded instructions','Stack bytes','Spill annotations','Reload annotations','Saved XMM slots','Static branches'],rows)
rows=[]
for label,item in shapes.items():
    rows.append([label,item['dense_loop_bytes'],item['dense_static_instructions'],
        item['dense_counts'].get('vmulps',0),item['dense_counts'].get('vaddps',0),
        item['dense_counts'].get('vbroadcastss',0),item['output_conditional_branches']])
text+=table(['Selected CLIP build','Dense body bytes','Body instructions','Vector multiplies','Vector adds','Broadcasts','Output conditional branch sites'],rows)
text+='''Dense counts are static per emitted loop body, not total dynamic operations.
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

'''
rows=[]
for label,trial in a['candidates'].items():
    if 'failure' in trial:
        rows.append([label,'REJECTED before performance',trial['failure']['phase'],trial['failure']['error']]);continue
    c=p.common.load(p.ROOT/('correctness-'+label+'.json'))
    rows.append([label,f"{c['head']['head_bit_comparisons']:,}",f"{c['extra_special_heads']:,}",
        f"{c['oracle']['transitions']:,} / {c['oracle']['nulls']:,}"])
text+=table(['Candidate','Original head bit checks','Extra Stage 1 special heads','Legal/null transitions'],rows)
text+='''The original suite includes 256 golden FENs, both perspectives, deep legal
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

'''
for label,trial in a['candidates'].items():
    if not trial['micro']:continue
    text+='### '+label+'\n\n'
    text+=table(['Frames','Stage 1 ns [IQR]','Candidate ns [IQR]','Paired factor','Repeat-only 95%'],[
        [r['frames'],f"{r['baseline']['median']:.2f} [{r['baseline']['q1']:.2f}, {r['baseline']['q3']:.2f}]",
         f"{r['candidate']['median']:.2f} [{r['candidate']['q1']:.2f}, {r['candidate']['q3']:.2f}]",
         factor(r['paired_speedup']['median']),ci(r['repeat_only95'])] for r in trial['micro']])
text+='''## Whole-engine throughput

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

'''
for label,trial in a['candidates'].items():
    if not trial['search']:continue
    text+='### '+label+'\n\n'
    text+=table(['Control','Paired factor','Grouped 95%','Position range','Baseline-first / candidate-first medians'],[
        [control(r),factor(r['factor']),ci(r['grouped95']),ci(r['position_range']),
         factor(r['order_medians']['baseline_first'])+' / '+factor(r['order_medians']['candidate_first'])] for r in trial['search']])
    load=trial['background_load']['other_cpu_percent_estimate']
    text+=f"Runtime {trial['runtime_seconds']/60:.1f} minutes; {trial['search_records']} primary searches. Background load median {load['median']:.2f}%, range {load['minimum']:.2f}–{load['maximum']:.2f}% of total logical capacity after subtracting benchmark processes; not CPU0 contention or thermal telemetry.\n\n"
    rows=[]
    for fixture in p.common.load(p.ROOT/'positions.json'):
        rows.append([fixture['id']]+[factor(r['paired_speedup']['median']) for r in trial['per_position'] if r['position']==fixture['id']])
    text+=table(['Fixture','200k','1M','100 ms','500 ms','1000 ms'],rows)
    text+=f"Material fixture/control medians (>3% elapsed): **{len(trial['material_regressions'])}**.\n\n"
    if trial['material_regressions']:
        text+=table(['Fixture','Control','Factor','Elapsed regression'],[[r['position'],control(r),factor(r['factor']),f"{r['elapsed_percent']:.2f}%"] for r in trial['material_regressions']])
text+='### Hidden-clipping endgame anomaly: saved-record audit\n\n'
text+=table(['Pass','Order','Factor','Baseline / candidate nodes','Baseline / candidate depth','Wall seconds, baseline / candidate'],[
    [r['repeat']+1,' / '.join(r['order']),factor(r['factor']),f"{r['baseline_nodes']:,} / {r['candidate_nodes']:,}",
     f"{r['baseline_depth']} / {r['candidate_depth']}",f"{r['baseline_wall']:.6f} / {r['candidate_wall']:.6f}"] for r in diagnosis['rows']])
text+=f'''The 100-ms piece-endgame median factor is {factor(diagnosis['median'])};
repeat-only bootstrap interval {ci(diagnosis['repeat_only95'])} crosses one.
There are {diagnosis['candidate_wins']} winning and {diagnosis['candidate_losses']}
losing pairs. Engine-reported times are exactly 100 ms and protocol wall overhead
is small, so a large protocol delay does not explain the loss. Rates vary and
some searches cross a completed-depth boundary. Order medians are
{factor(diagnosis['baseline_first_median'])} baseline-first /
{factor(diagnosis['candidate_first_median'])} candidate-first; segment-load
correlation is {diagnosis['speedup_load_correlation']:.3f}, only an observational
association. This does not prove a repeatable kernel defect or establish a
specific scheduling, frequency, cache or branch cause.

No pair was removed, relabeled or replayed. The material median remains
unexplained, so the candidate is not accepted despite positive aggregate bounds.
The predeclared extension rule excludes material fixture/order failures; neither
trial was extended beyond seven passes. This audit ran **zero new searches**.
The promising implementation is preserved without weakening its acceptance gate.

'''
text+='''Complete per-position CSV includes median NPS/time, nodes, depths, evaluation
calls and qnodes. JSON also retains paired quartiles and within-position repeat CV.
Absolute NPS from sequential variant trials is not treated as a matched comparison
between those candidates. No unverified combined speedup is calculated.

## Acceptance, classical context and remaining work

'''
text+=table(['Candidate','Decision','Micro support','Search intervals','Order support','No material fixture loss'],[
    [label,trial['status'],trial.get('gates',{}).get('representative_micro_support','failed correctness'),
     trial.get('gates',{}).get('all_search_intervals_positive','—'),trial.get('gates',{}).get('long_control_orders_positive','—'),
     trial.get('gates',{}).get('no_material_fixture_regressions','—')] for label,trial in a['candidates'].items()])
text+='''Acceptance requires every numerical/search gate, faster representative rotating
heads with no material common-head loss, positive grouped support across search
controls/orders, and no unexplained >3% fixture median elapsed regression. Three
percent is a practical target, not a mandatory minimum gain. Micro-only gains or
one positive timed control cannot justify acceptance.

'''
if context['performed']:
    text+='Fresh optional three-way context: three rotated triples on all 12 fixtures at 1000 ms, **108 searches**.\n\n'
    text+=table(['NNUE build','NNUE/classical wall-NPS ratio','Grouped 95%'],[[b,factor(r['nnue_classical_ratio']),ci(r['grouped95'])] for b,r in context['summary'].items()])
    text+='Different evaluators visit different trees: these matched-position NPS ratios are practical throughput context, not equal-tree inference cost or playing strength. They are not pooled into acceptance tests.\n\n'
else:
    text+='Optional fresh classical comparison was **not run** because no candidate passed the primary gates. No old scalar/Classical ratio is projected into a claimed new recovery or Elo result.\n\n'
text+=f'''Fresh sampled head fraction is approximately {100*head_share:.2f}%.
If that fraction were representative and other costs fixed, a hypothetical 1.5×
head speedup would imply `1 / ((1-f) + f/1.5)` =
{1/((1-head_share)+head_share/1.5):.3f}× whole speed. This is an Amdahl planning
estimate, not a measured result or a promise; actual matched search tables take
precedence. The dense arithmetic remains required under this bitwise contract.

## Final answers

1. **Largest head cost:** dense hidden-layer math, with {prof['counts']['dense_loop']}
   samples versus {prof['counts']['hidden_clip_and_output']} in hidden clipping/output.
2. **Compiler strengths:** four independent YMM neuron groups, contiguous
   transposed weights, register-resident hidden chains and effective input clipping.
3. **Attempted changes:** independent four-way loop unrolling and vector hidden
   clipping using the already verified helper. No alternative reduction tree.
4. **Head latency:** the four working-set tables above give the actual paired
   effects and variation; faster arithmetic alone is not accepted as a search gain.
5. **Whole engine:** use each candidate's five matched controls and per-position
   failures. Overall decision: **{a['decision']}**.
6. **Exact Stage 1-relative speedups:** all five point estimates and grouped
   intervals are tabulated; no original-scalar comparison substitutes for Stage 1.
7. **Evaluation bits:** accepted/performance-tested candidates pass the original
   suite plus 4,352 frozen mixed-special-value production outputs. Any rejected
   numerical candidate is explicitly identified before timing.
8. **Fixed work:** all performance-tested moves, scores, PVs, nodes, completed
   depths, evaluations, qnodes and counters/iteration snapshots are identical.
9. **Fixture regressions:** every material median is listed; none is hidden by
   an aggregate. Timed-search decisions may differ with completed work.
10. **Decision:** **{a['decision']}**; experimental retained choice
    **{a['retained_baseline']}**. The production default remains classical.
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

**{preserved['checked_files']}/{preserved['checked_files']} protected files unchanged.**
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
'''
summary=[]
for label,trial in a['candidates'].items():
    if not trial['search']:
        summary.append([label,'—','—','—','—','—',trial['status']]);continue
    fixed=next(r for r in trial['search'] if r['budget']==1000000)
    timed=next(r for r in trial['search'] if r['budget']==1000)
    head=next(r for r in trial['micro'] if r['frames']==128)
    summary.append([label,factor(fixed['factor']),ci(fixed['grouped95']),factor(timed['factor']),
        ci(timed['grouped95']),factor(head['paired_speedup']['median']),trial['status']])
summary=table(['Variant','1M factor','1M grouped 95%','1000-ms factor','1000-ms grouped 95%','128-frame head factor','Status'],summary)
text=text.replace('## Exact baseline, model and environment',summary+'## Exact baseline, model and environment',1)
for path in [p.REPO/'NNUE_STAGE3_OPTIMIZATION_REPORT.md',p.ROOT/'NNUE_STAGE3_OPTIMIZATION_REPORT.md']:
    path.write_text(text,encoding='utf-8')
print('Wrote report',a['decision'],len(text.split()),'words')
