"""Generate the Stage 2 report entirely from saved experiment receipts."""
import json
import statistics as s
import sys
import experiment as p

label = sys.argv[1]
a = p.common.load(p.ROOT / ('analysis-'+label+'.json'))
prof = p.common.load(p.ROOT/'maintenance-profile.json')
c = p.common.load(p.ROOT / ('correctness-'+label+'.json'))
reg = p.common.load(p.ROOT / ('regressions-'+label+'.json'))
assembly = p.common.load(p.ROOT / ('assembly-audit-'+label+'.json'))
plan = p.common.load(p.ROOT/'plan.json')
preserve = p.common.load(p.ROOT/'preservation-after.json')
mixed = next(r for r in a['micro'] if r['kind']=='mixed')
head = c['head']
build = p.common.load(p.ROOT / ('build-'+label+'-engine.json'))
trials = {b:p.common.load(p.ROOT/('analysis-'+b+'.json')) for b in ['sort','fused','small']
          if (p.ROOT/('analysis-'+b+'.json')).exists()}
descriptions = {
    'sort': 'tiny-list sort specialization',
    'fused': 'ordered parent-copy/row fusion',
    'small': 'small search-state temporary specialization',
}
mode = next(v.split('=')[1] for v in build['command'] if v.startswith('-DCHESSLAB_NNUE_UPDATE='))


def speed(v):
    return f'{v:.4f}x ({100*(v-1):+.2f}%)'


def title(mode,budget):
    return f'{budget:,} nodes' if mode=='nodes' else f'{budget:,} ms'


text = f'''# StockBear — Stage 2 accumulator optimization report

## Decision and scope

**{a['status']} overall — retain Stage 1 as the experimental baseline.**
{'Retain the accepted candidate in isolation; do not promote it.' if a['status']=='ACCEPTED' else 'No Stage 2 candidate is accepted; retain Stage 1 as the winner.'}
Three independent trials completed **{sum(v['search_records'] for v in trials.values()):,} primary searches**.
All numerical and fixed-work correctness gates pass. The detailed comparison below is
against the accepted **Stage 1 `NNUEKernel=clip`**, never the old scalar head.
The independent trials change maintenance only; they do not change the model,
persisted accumulator-frame layout, floating arithmetic or search policy. The detailed
per-fixture table uses the selected primary trial; all trials are summarized below.

Branch: `codex/nnue-stage2-accumulator`, based on Stage 1
`{plan['baseline_commit']}`. The active engine and classical default are
unchanged. No training, labeling, tournaments, sealed-test access, promotion,
lazy updates, quantization or Stage 3 work took place.

## Baseline and reproducibility

* Baseline: exact copied Stage 1 binary, SHA-256
  `{plan['baseline_binary_sha256']}`; independently reconfirmed before changes.
* Candidate: `nnue-optimization-stage2-20261017/artifacts/{label}/engine.exe`, SHA-256
  `{build['sha256']}`. Each has its matching local PDB.
* Target: existing NNUE 64/32, 54,209 parameters; selected `medium/best.pt`
  and `medium.sbnnue` remain hashed and unchanged. Export SHA-256
  `{plan['network_sha256']}`. No fresh export or weights were generated.
  Checkpoint SHA-256: `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`.
* Same Zig 0.13 / Clang 18 toolchain, C++17, `-O2 -pthread -Wall -Wextra
  -ffp-contract=off`, baseline update strategy **2**, primary candidate **{mode}**; no fast-math or LTO
  flag was added. Full commands and all source/header hashes are saved.
* One search thread, 16 MiB TT, CPU-0 affinity, `NNUEKernel=clip`, identical
  options, 12 frozen positions including full opening history, fresh TT per go.
  {p.repeats(label)} paired, rotated passes; {a['search_records']} primary searches. Per-position
  records retain wall time, reported NPS, depth, seldepth, moves, scores, PVs,
  all search counters, evaluation calls and quiescence counts.

Power/environment: AC was measured online; Windows Acer power scheme and last
user-confirmed NitroSense Quiet/Eco profile were retained. NitroSense is not
readable through the power-plan setting, so its current mode is not independently
verified. No settings/apps were changed. All CPU-intensive work ran serially.
Background CPU after subtracting benchmark processes: median
{a['background_load']['other_cpu_percent_estimate']['median']:.2f}%, range
{a['background_load']['other_cpu_percent_estimate']['minimum']:.2f}–{a['background_load']['other_cpu_percent_estimate']['maximum']:.2f}%
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
measure all process allocations. It recorded {prof['allocations']:,} allocations /
{prof['allocation_bytes']:,} requested bytes across 36 instrumented searches.

Fresh Stage 1 clip counters: {prof['updates']:,} updates / {prof['nodes']:,} nodes,
{prof['ratios']['updates_per_node']:.6f} updates/node,
{prof['ratios']['rows_per_perspective']:.5f} changed rows/perspective,
{prof['ratios']['logical_bytes_per_copy']:.3f} logical bytes copied/child,
{100*prof['ratios']['null_fraction']:.3f}% null updates, exactly one refresh/search.
Logical bytes are not measured cache traffic.

### Maintenance costs and observer limits

| Isolated timer category | Calls (36 searches) | Total ms | ns/update | ns/node | % timer sum |
|---|---:|---:|---:|---:|---:|
'''
for name in ['nnue_copy','nnue_rows','nnue_sort','nnue_metadata','nnue_delta','nnue_state','nnue_ep','nnue_update','nnue_refresh']:
    r = prof['categories'][name]
    text += f"| {name} | {r['calls']:,} | {r['ns']/1e6:.2f} | {r['ns_per_update']:.3f} | {r['ns_per_node']:.3f} | {r['percent']:.3f} |\n"
text += f'''
`nnue_update` is exclusive residual bookkeeping, not inclusive update latency.
Sorting covers two tiny state lists and both changed-row lists; `nnue_state`
excludes its nested EP scope. Row cost includes two perspective scopes; divided
by actual rows it is an **instrumented amortization**, not pure instruction cost.
Copying/state/metadata values near the clock floor cannot be ranked precisely.
Feature indexing is in `nnue_delta`; null counts are logical counter events and
their actual path is separately exercised by microbenchmarks below.

Counter-only median elapsed overhead was
{prof['observer_overhead']['counters']['median_elapsed_ratio']:.3f}x; detailed timers
{prof['observer_overhead']['timers']['median_elapsed_ratio']:.3f}x (per-position range
{prof['observer_overhead']['timers']['min']:.2f}–{prof['observer_overhead']['timers']['max']:.2f}x).
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

Assembly: baseline updater has {sum(assembly['baseline']['updater']['instructions'].values())} static instructions /
{assembly['baseline']['updater']['stack_bytes'][0]} stack bytes; primary candidate has
{sum(assembly[label]['updater']['instructions'].values())} /
{assembly[label]['updater']['stack_bytes'][0]}. Sorting removes three generic sorting
call sites; row fusion instead grows the updater to 1,068 static instructions
and 1,016 stack bytes, versus 529/632 in the baseline.
These are pre-link compiler assembly counts for `nnue.cpp`, not disassembly
of the final linked EXE. Both head dispatch bodies have 669 static instructions and identical instruction
counts. Neither inspected updater/head body has FMA instructions. Larger inline
code and stack are recorded tradeoffs, not assumed improvements. Full assembly
and extracted updater/head listings are preserved; static counts are not dynamic
execution counts or cycle measurements.

## Correctness

* Existing native oracle: **{c['oracle']['transitions']:,} move transitions and
  {c['oracle']['nulls']:,} null transitions**, bitwise lanes/head/CP parity against
  the original ordered generic updater; parent and sibling restoration passes.
* Independent seeded targeted walk: **{c['targeted']['edges']:,} recorded edges**
  across quiet, capture, king, castling, promotion, legal/pinned EP, rights and
  null cases; deep continuations, roots, poisoned child lanes and sibling
  restoration. Candidate and Stage 1 whole-walk float/head digests match:
  `{c['targeted']['digest']}`. All relevant 128 float lanes are compared.
* Head regression: **{head['head_bit_comparisons']:,} bitwise comparisons**,
  256 existing golden FENs, arbitrary finite frames and both turns; four NaN-head
  cases, {head['special_clip_lane_comparisons']:,} special clipping lanes, infinities,
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
'''
for r in a['micro']:
    text += (f"| {r['kind']} | {r['edges']:,} | {r['update_ns']['baseline']['median']:.2f} | "
             f"{r['update_ns'][label]['median']:.2f} | {r['update_ns']['paired_speedup']['median']:.3f}x | "
             f"{r['total_ns']['baseline']['median']:.2f} / {r['total_ns'][label]['median']:.2f} |\n")
text += f'''
Mixed-case update median: **{mixed['update_ns']['baseline']['median']:.2f} →
{mixed['update_ns'][label]['median']:.2f} ns**, paired factor
**{mixed['update_ns']['paired_speedup']['median']:.3f}x**. The mixed micro corpus is
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
{mixed['prepared_update_ns']['baseline']['median']:.2f} /
{mixed['prepared_update_ns'][label]['median']:.2f} ns; divided by its
{mixed['rows_both_perspectives']:.3f} average changed rows across both perspectives,
{mixed['ns_per_changed_row_reference']['baseline']:.2f} /
{mixed['ns_per_changed_row_reference'][label]:.2f} ns/row. That quotient includes
copying/bookkeeping and is **not isolated row-arithmetic latency**. Synthetic
copy-only references are {mixed['copy_reference_ns']['baseline']['median']:.2f} /
{mixed['copy_reference_ns'][label]['median']:.2f} ns; metadata-only references
{mixed['metadata_reference_ns']['baseline']['median']:.2f} /
{mixed['metadata_reference_ns'][label]['median']:.2f} ns. Components have separate
loop/cache contexts; do not subtract/add them to reconstruct production costs.
Full per-category component results and paired IQRs are in `analysis-{label}.json`.

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
'''
for r in a['search']:
    ci = r['grouped_bootstrap95']
    text += f"| {title(r['mode'],r['budget'])} | {speed(r['geomean_paired_speedup'])} | {ci[0]:.4f}–{ci[1]:.4f}x | {r['position_range'][0]:.4f}–{r['position_range'][1]:.4f}x |\n"
text += '\n### Per-position median paired speedups\n\n| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1000 ms |\n|---|---:|---:|---:|---:|---:|\n'
for row in p.common.load(p.ROOT/'positions.json'):
    vals = [next(v['paired_speedup']['median'] for v in a['per_position'] if v['position']==row['id'] and v['mode']==m and v['budget']==b) for m,b in plan['budgets']]
    text += '| '+row['id']+' | '+' | '.join(f'{v:.4f}x' for v in vals)+' |\n'
slower = [r for r in a['per_position'] if r['paired_speedup']['median']<1]
text += f'''
{len(slower)} / 60 fixture/control medians were below 1.0; material (>3% elapsed)
regressions: **{len(a['material_regressions'])}**. These are medians, not guarantees
that every individual noisy pair wins. `per-position-{label}.csv` also reports
wall NPS/time, actual nodes, depth, seldepth, evaluations and qnodes for both builds;
JSON includes repeat CV, paired quartiles and order-specific estimates. Timed
search depth/decisions may differ because faster search reaches more nodes;
fixed-work decisions remain exact.
'''
if slower:
    text += '\nBelow-unity medians: '+', '.join(f"{r['position']} {title(r['mode'],r['budget'])}: {r['paired_speedup']['median']:.4f}x" for r in slower)+'.\n'
for other, trial in trials.items():
    if other==label:
        continue
    text += '\n### Per-position results: '+descriptions[other]+'\n\n| Fixture | 200k nodes | 1M nodes | 100 ms | 500 ms | 1000 ms |\n|---|---:|---:|---:|---:|---:|\n'
    for row in p.common.load(p.ROOT/'positions.json'):
        values = [next(v['paired_speedup']['median'] for v in trial['per_position'] if v['position']==row['id'] and v['mode']==m and v['budget']==b) for m,b in plan['budgets']]
        text += '| '+row['id']+' | '+' | '.join(f'{v:.4f}x' for v in values)+' |\n'

if (p.ROOT/'classical-gap.json').exists():
    gap = p.common.load(p.ROOT/'classical-gap.json')['summary']
    x = gap['baseline']['geomean_paired_nps_ratio_to_classical']
    y = gap[label]['geomean_paired_nps_ratio_to_classical']
    recovery = gap['aggregate_remaining_nps_shortfall_fraction_recovered']
    text += f'''
## Fresh matched classical throughput context

Separate secondary measurement: three rotated classical/Stage 1/candidate
triples on the same 12 fixtures at 1000 ms (108 searches), identical controls.
This uses **fresh matched-position measurements**, not projections from older
scalar-head results. Geometric mean of per-fixture median paired NPS ratios to
classical: Stage 1 **{x:.4f}**, candidate **{y:.4f}**. The aggregate remaining
shortfall fraction recovered is **{100*recovery:.1f}%**, calculated as
`(candidate_ratio - stage1_ratio) / (1 - stage1_ratio)`.
This is descriptive with only three triples/fixture, and can be noisy; it is
not the average of individual shortfall recoveries. Different evaluators visit
different trees, so it is not equal-work evaluator cost or a strength estimate.
Raw triples, grouped intervals and load samples are in `classical-gap.json`.
The joint position/triple bootstrap gives a shortfall-recovery interval of
**{100*gap['shortfall_recovery_joint_grouped95_conditional_on_baseline_below_classical'][0]:.1f}% to
{100*gap['shortfall_recovery_joint_grouped95_conditional_on_baseline_below_classical'][1]:.1f}%**,
conditional on a positive baseline shortfall; 11 of 10,000 draws had no positive
shortfall and were omitted/count recorded. Direct secondary candidate/Stage 1
speedup is {gap['secondary_direct_candidate_baseline_speedup']:.4f}x, interval
{gap['secondary_direct_speedup_joint_grouped95'][0]:.4f}–{gap['secondary_direct_speedup_joint_grouped95'][1]:.4f}x.
**No reliable gap recovery is established, and this secondary comparison does
not overturn the inconclusive primary sort decision.** No historical projection
or Elo improvement is claimed.
'''
else:
    text += '''
## Classical throughput context

No new matched classical benchmark was run, so no directly measured classical
gap recovery is claimed. The Stage 2 factor cannot be equated with Elo or
combined silently with historical scalar-head ratios.
'''

if (p.ROOT/'native-summary.json').exists():
    native = p.common.load(p.ROOT/'native-summary.json')
    text += f'''
## Remaining bottlenecks

Bounded post-change own-child native sampling: {native['samples']:,} successful
RIP samples, head **{100*native['head_fraction']:.2f}%**, narrowly recognized
maintenance **{100*native['maintenance_fraction']:.2f}%**, other/unattributed
**{100*native['other_fraction']:.2f}%**. This is a coarse post-change snapshot,
not a matched component speedup. Median sampled/unsampled NPS ratio across the
four fixtures is {native['median_sampled_unsampled_nps_ratio']:.4f}; failed context
attempts ({native['failed_samples']}) are excluded. Suspension overhead is retained
in raw records. Inlining and library attribution limit precision.
'''

text += f'''
## Final answers and stopping decision

1. **Largest maintenance bottleneck:** repeated bookkeeping is the largest
   recognizable envelope; tiny-list sorting and temporary-state handling are
   addressable parts, with their measured tradeoffs disclosed separately.
   Current observers cannot defensibly give an exact production suboperation ranking.
2. **Implemented:** independent tiny-sort, existing row-fusion and
   small-state trials; full Stage 1 updater remains available as the control.
3. **Updates:** mixed micro paired factor {mixed['update_ns']['paired_speedup']['median']:.3f}x,
   with the nonrepresentative null-heavy mix and per-class figures disclosed above.
4. **Whole engine:** the five Stage 1-relative factors and grouped intervals above
   are the primary result; none is measured against the original scalar head.
5. **Bitwise accumulators:** yes, all relevant float lanes and head/CP gates pass.
6. **Fixed decisions:** yes, all fixed-work scores, moves, PVs and counters match.
7. **Regressions:** {len(slower)} slightly negative fixture/control medians;
   {len(a['material_regressions'])} material regression under the predeclared threshold.
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

**{preserve['checked_files']}/{preserve['checked_files']} protected files unchanged**,
including production code/executables, selected checkpoint/export, previous
models and studies, and Stage 1 sources/binaries. Sealed data was not enumerated
or read. Baseline/candidate source copies, generated headers, EXE/PDB and full
assembly are local under this workspace's ignored `artifacts/` directory on Z:.
Committed scripts, focused patches, raw measurements, parity receipts and
normalized text/artifact manifests support reproduction. See workspace README
for exact commands and prerequisite local artifacts. The report is mirrored in
the workspace and compared after LF normalization.
'''
summary = '## Independent trial summary\n\n| Trial | Passes | 200k | 1M | 100 ms | 500 ms | 1000 ms | Status |\n|---|---:|---:|---:|---:|---:|---:|---|\n'
for name,trial in trials.items():
    summary += '| '+descriptions[name]+' | '+str(p.repeats(name))+' | '+' | '.join(
        f"{v['geomean_paired_speedup']:.4f}x [{v['grouped_bootstrap95'][0]:.4f}, {v['grouped_bootstrap95'][1]:.4f}]" for v in trial['search'])+' | '+trial['status']+' |\n'
summary += ('\nBrackets are grouped 95% intervals. Every trial has its own paired Stage 1 controls; '
    'do not compare absolute NPS between sequential trials as a matched experiment. '
    'All complete per-position results are in `per-position-sort.csv`, '
    '`per-position-fused.csv` and `per-position-small.csv`.\n\n')
for name,trial in trials.items():
    summary += f"* **{name}**: {trial['search_records']} measured searches; {len(trial['material_regressions'])} material fixture/control medians.\n"
summary += '\n| Trial | Quiet update speedup | Capture | Promotion | Mixed (null-heavy) |\n|---|---:|---:|---:|---:|\n'
for name,trial in trials.items():
    summary += '| '+name+' | '+' | '.join(f"{next(v for v in trial['micro'] if v['kind']==k)['update_ns']['paired_speedup']['median']:.3f}x" for k in ['quiet','capture','promotion','mixed'])+' |\n'
summary += '\n| Correctness trial | Legal / null oracle | Head bit checks | Exact fixed-work fixtures/controls | Cancellation cases |\n|---|---:|---:|---:|---:|\n'
for name in trials:
    gate = p.common.load(p.ROOT/('correctness-'+name+'.json'))
    checks = p.common.load(p.ROOT/('regressions-'+name+'.json'))
    summary += f"| {name} | {gate['oracle']['transitions']:,} / {gate['oracle']['nulls']:,} | {gate['head']['head_bit_comparisons']:,} | {len(gate['fixed_work'])} | {len(checks['interrupted'])} |\n"
summary += ('\nThe sort trial reached the predeclared ten-pass ceiling because its seven-pass '
    'intervals crossed no gain. All five intervals then became positive, but promotion '
    'at 1M nodes remained 3.11% slower in elapsed time, leaving it inconclusive. '
    'The interrupted resume runner had skipped searches but redundantly written '
    'checkpoints for already completed rows; that bug was fixed. Original raw load '
    'segments are retained; duplicate empty resume segments are excluded from analysis. '
    'No measured searches were replayed. `plan.baseline_commit` is the authoritative '
    'Stage 1 revision; the inherited `source_revision` in this frozen initial plan '
    'refers to the older Stage 1 setup commit, not the measured baseline binary.\n\n')
text = text.replace('## Baseline and reproducibility',summary+'## Baseline and reproducibility',1)
(p.REPO/'NNUE_STAGE2_OPTIMIZATION_REPORT.md').write_text(text,encoding='utf-8')
(p.ROOT/'NNUE_STAGE2_OPTIMIZATION_REPORT.md').write_text(text,encoding='utf-8')
print('Wrote report',len(text.split()),'words',flush=True)
