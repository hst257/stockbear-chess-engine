"""Generate the final Stage 2.1 report from saved receipts only."""
import collections
import json
import statistics as s
import experiment as p

a=p.common.load(p.ROOT/'analysis.json')
w=p.common.load(p.ROOT/'workload.json')
d=p.common.load(p.ROOT/'promotion-diagnosis.json')
plan=p.common.load(p.ROOT/'plan.json')
micro=p.common.load(p.ROOT/'micro.json')
preserved=p.common.load(p.ROOT/'preservation-after.json')
new=a['candidates']['selective'];old=a['candidates']['sort']
status=new['status']


def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n|'+ '|'.join(['---']*len(headers))+'|\n'+''.join('| '+' | '.join(map(str,row))+' |\n' for row in rows)+'\n'


def factor(v):return f'{v:.4f}×'
def ci(v):return f'[{v[0]:.4f}, {v[1]:.4f}]'
def title(r):return f"{r['budget']:,} {'nodes' if r['mode']=='nodes' else 'ms'}"


text=f'''# StockBear — Stage 2.1 targeted tiny-list sorting report

## Executive decision

**Refined candidate: {status}.**
{'Preserve the refined implementation as an isolated experiment; do not promote it.' if status=='ACCEPTED' else 'Retain accepted Stage 1 as the experimental baseline; no refined candidate met every acceptance gate.'}
One new candidate was implemented: lengths 0–2 use an explicit no-op or one
strict compare/swap; larger state/changed-row lists retain `std::sort`.
The prior full insertion-sort comparator remains separately selectable and is
**{old['status']}** in this fresh study. No rejected Stage 2 fusion/state changes
were combined. The active StockBear executable and classical default are unchanged.

The original promotion slowdown did **not reproduce reliably** in the small
pre-implementation diagnostic. That result alone neither accepts the old sort
nor establishes its original slowdown's cause. This report separates diagnosis,
counter-only observation, microbenchmarks, and the predeclared full search.

## Frozen baseline, isolation and limits

Branch: `codex/nnue-stage2-1-tiny-sort`, primary parent Stage 1
`{plan['baseline_commit']}`. Prior Stage 2 evidence is preserved at
`{plan['stage2_commit']}` and copied reference hashes are archived locally.
There were no routine intermediate commits in this follow-up.
`baseline_commit` identifies the measured baseline; the inherited historical
`source_revision` field in the frozen plan refers to the earlier Stage 1 setup.

* Accepted baseline: exact Stage 1 `NNUEKernel=clip`, compact strategy 2;
  SHA-256 `{plan['baseline_binary_sha256']}`.
* Imported Stage 2 full insertion-sort binary:
  `{plan['stage2_sort_binary_sha256']}`.
* Refined binary:
  `{p.common.load(p.ROOT/'build-selective-engine.json')['sha256']}`.
* Model remains 780 → dual 64 → 32 → 1, 54,209 parameters. Export SHA-256
  `{plan['network_sha256']}`; checkpoint SHA-256
  `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`.
* Identical Zig 0.13/Clang 18, C++17, `-O2 -pthread -Wall -Wextra
  -ffp-contract=off`; no added fast-math, reassociation, FMA contraction or LTO.
* One search thread, CPU0 affinity, 16 MiB hash, fresh TT per go, no pondering,
  identical FENs/full histories, identical search options and `clip`.
* {a['repeats']} rotated three-way passes × 16 positions × five controls =
  **{a['search_records']:,} primary searches**. Search schedule wall runtime:
  {a['runtime_seconds']/60:.1f} minutes; predeclared cap 45 minutes, maximum ten
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
{a['background_load']['other_cpu_percent_estimate']['median']:.2f}%, range
{a['background_load']['other_cpu_percent_estimate']['minimum']:.2f}–{a['background_load']['other_cpu_percent_estimate']['maximum']:.2f}%
of total logical capacity. This is not CPU0 contention or boost/thermal telemetry.

## Promotion regression diagnosis

'''
rows=[]
for group in ['original','diagnostic']:
    for r in d[group]:
        rows.append([group,r['position'],factor(r['median']),ci(r['repeat_bootstrap95']),
            factor(r['baseline_first_median']),factor(r['candidate_first_median']),f"{r['speedup_background_correlation']:.3f}"])
text+=table(['Study','Fixture','Full sort / Stage 1','Repeat-only 95%','Baseline first','Sort first','Load correlation'],rows)
text+='''The original 10-pair promotion result has a repeat-bootstrap interval crossing
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

'''
rows=[]
for type_ in ['state','rows']:
    total=w['aggregate'][type_]['calls']
    for length,count in sorted(w['lengths'][type_].items(),key=lambda r:int(r[0])):
        rows.append([type_,length,f'{count:,}',f'{100*count/total:.3f}%'])
text+=table(['List','Length','Calls','Share'],rows)
rows=[]
for type_ in ['state','rows']:
    r=w['aggregate'][type_];total=r['calls']
    rows.append([type_,f"{total:,}",f"{100*r['sorted']/total:.2f}%",f"{100*r['reverse']/total:.2f}%",r['equal'],
        f"{r['comparisons']:,}",f"{r['shadow_insertion_comparisons']:,}",f"{r['shadow_insertion_moves']:,}"])
text+=table(['List','Calls','Already sorted','Reverse sorted','Equal-key calls','Reference comparisons','Shadow insertion comparisons','Shadow shifts'],rows)
text+='''Sorted/reverse categories overlap for length 0/1 or equal lists. No equal keys
were observed. Legal orthodox piece removals/additions use distinct piece-square
features; captured pieces have a different color feature, and intersecting old/new
state features cancel before row creation. Piece and state feature ranges are
disjoint. No general duplicate-free API assumption is imposed by the new helper:
synthetic equal-key identity is also checked against the reference.

'''
text+=table(['Originating search routine','Calls per list type'],[[name,f'{count:,}'] for name,count in w['phase']['rows'].items()])
text+=table(['Transition class','Calls per list type'],[[name,f'{count:,}'] for name,count in w['move_class']['rows'].items()])
text+=f'''Phase labels describe the parent routine issuing the update, not the child's
eventual visit type. Key histograms use 49-wide bins and are retained by
phase/move/type/length in `workload-raw.jsonl`; state indices are at 768–779,
signed row magnitudes span 1–780. Per-promotion/castling/EP distributions remain
available in the raw buckets.

Observer wall-time multiplier versus matched Stage 1: median
**{w['observer_elapsed_multiplier']['median']:.3f}×**, range
{w['observer_elapsed_multiplier']['minimum']:.3f}–{w['observer_elapsed_multiplier']['maximum']:.3f}×.
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

'''
rows=[]
for label in ['sort','selective']:
    c=p.common.load(p.ROOT/('correctness-'+label+'.json'))
    rows.append([label,f"{c['sorting']['tests']:,}",c['sorting']['equal_key_identity_mismatches'],
        f"{c['oracle']['transitions']:,} / {c['oracle']['nulls']:,}",f"{c['head']['head_bit_comparisons']:,}",len(c['fixed_work'])])
text+=table(['Implementation','Sorting cases','Equal-key identity mismatches','Legal/null transitions','Head bit checks','Fixed-work comparisons'],rows)
text+='''Sorting cases cover lengths 0–16, random/permuted/sorted/reverse inputs,
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

'''
rows=[]
for r in new['micro']:
    other=next(v for v in old['micro'] if v['kind']==r['kind'])
    values=r['update_ns']
    rows.append([r['kind'],f"{values['baseline']['median']:.2f}",f"{other['update_ns']['sort']['median']:.2f}",
        f"{values['selective']['median']:.2f} [{values['selective']['q1']:.2f}, {values['selective']['q3']:.2f}]",
        factor(other['update_ns']['paired_speedup']['median']),factor(values['paired_speedup']['median']),
        f"{r['total_ns']['baseline']['median']:.2f} / {r['total_ns']['selective']['median']:.2f}"])
text+=table(['Class','Stage 1 ns','Full sort ns','Refined ns [IQR]','Full / Stage 1','Refined / Stage 1','Delta+update ns, base / refined'],rows)
text+='''Update includes state extraction, lane copying, metadata and ordered rows;
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

'''
for type_,name in [(1,'Signed rows'),(0,'State-key integers')]:
    text+='#### '+name+'\n\n'
    rows=[]
    for r in new['sort_micro']:
        if r['type']!=type_:continue
        oldr=next(v for v in old['sort_micro'] if v['length']==r['length'] and v['type']==type_)
        rows.append([r['length'],f"{r['baseline']['median']:.2f}",f"{oldr['candidate']['median']:.2f}",
            f"{r['candidate']['median']:.2f}",factor(r['paired_speedup']['median'])])
    text+=table(['Length','Stage 1 ns','Full sort ns','Refined ns','Refined paired factor'],rows)
text+='''## Whole-engine throughput and uncertainty

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

'''
for suite,name in [('frozen12','Frozen 12'),('supplementary4','Supplementary promotion 4 (exploratory)')]:
    text+='### '+name+'\n\n'
    rows=[]
    for r in new['suites'][suite]:
        prior=next(v for v in old['suites'][suite] if v['mode']==r['mode'] and v['budget']==r['budget'])
        rows.append([title(r),factor(prior['geomean_paired_speedup'])+' '+ci(prior['grouped_bootstrap95']),
            factor(r['geomean_paired_speedup'])+' '+ci(r['grouped_bootstrap95']),
            ' / '.join(factor(v) for v in r['order_medians'].values())])
    text+=table(['Control','Full sort / Stage 1 [95%]','Refined / Stage 1 [95%]','Refined order subset medians'],rows)
text+='### Direct refined versus full insertion sort, frozen suite\n\n'
text+=table(['Control','Paired factor','Grouped 95%'],[[title(r),factor(r['factor']),ci(r['grouped95'])] for r in a['selective_vs_stage2_sort']])
text+='### Baseline drift sensitivity\n\n'
text+=table(['Control','Lowest / highest normalized baseline pass'],[
    [title(r),factor(r['minimum'])+' / '+factor(r['maximum'])] for r in a['baseline_drift']])
text+='Each baseline pass is normalized to each fixture\'s across-pass median NPS, then geometrically averaged across the frozen suite. Drift is an environmental sensitivity signal, not measured throttling or a correction applied to results.\n\n'
for label,trial in [('selective',new),('sort',old)]:
    text+=f'### Per-position factors: {label}\n\n'
    rows=[]
    for fixture in p.common.load(p.ROOT/'positions.json')+p.common.load(p.ROOT/'supplementary-positions.json'):
        entries=[r for r in trial['per_position'] if r['position']==fixture['id']]
        rows.append([fixture['id']]+[factor(r['paired_speedup']['median']) for r in entries])
    text+=table(['Fixture','200k','1M','100 ms','500 ms','1000 ms'],rows)
    text+=f"Material fixture/control medians (>3% elapsed): **{len(trial['material_regressions'])}**.\n\n"
    if trial['material_regressions']:
        text+=table(['Fixture','Control','Factor'],[[r['position'],title(r),factor(r['speedup'])] for r in trial['material_regressions']])
text+='''`per-position-*.csv` additionally reports wall NPS/time, nodes, depth, seldepth,
evaluation calls and qnodes. JSON includes paired IQRs, repeat CV and order
subsets. Timed searches can reach different nodes/depths while all fixed-work
decisions remain identical. No inference about playing strength is made.

## Generated assembly

'''
rows=[]
for label in ['sort','selective']:
    assembly=p.common.load(p.ROOT/('assembly-audit-'+label+'.json'))
    for build in ['baseline',label]:
        if label=='selective' and build=='baseline':continue
        body=assembly[build]['updater']
        rows.append([build,sum(body['instructions'].values()),body['stack_bytes'],
            sum(v for k,v in body['instructions'].items() if k.startswith('j')),
            sum('sort' in name for name in body['calls']),body['fma']])
text+=table(['Updater','Static instructions','Stack bytes','Static jump instructions','Sort call sites','FMA'],rows)
linked=p.common.load(p.ROOT/'linked-symbol-sizes.json')['builds']
text+=table(['Linked executable','Updater symbol bytes','Head symbol bytes'],[
    [label,values['nnue_update_search_states'].get('function_bytes','unavailable'),
     values['nnue_side_to_move'].get('function_bytes','unavailable')] for label,values in linked.items()])
text+='''Listings come from `nnue.cpp -S` with recorded strict flags, before final
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

'''
text+=table(['Candidate','Decision','All frozen intervals positive','Long promotion controls','Both long-control orders','Material medians'],[
    [label,trial['status'],
     'yes' if trial['gate_checks']['all_frozen_control_intervals_positive'] else 'no',
     'positive' if trial['gate_checks']['supplementary_long_controls_positive'] else 'not established',
     'positive' if trial['gate_checks']['long_control_order_subsets_positive'] else 'not established',
     len(trial['material_regressions'])] for label,trial in [('sort',old),('selective',new)]])
one_million=next(r for r in new['suites']['frozen12'] if r['budget']==1000000)
one_second=next(r for r in new['suites']['frozen12'] if r['budget']==1000)
quiet=next(r for r in new['micro'] if r['kind']=='quiet')['update_ns']['paired_speedup']['median']
capture=next(r for r in new['micro'] if r['kind']=='capture')['update_ns']['paired_speedup']['median']
promotion=next(r for r in new['micro'] if r['kind']=='promotion')['update_ns']['paired_speedup']['median']
text+=f'''Acceptance requires all exact gates, positive frozen-suite control intervals,
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
   **{status}** and prior full-sort status is **{old['status']}**. The refinement
   does not establish a robust whole-search advantage over the full sort;
   microbenchmark winners vary by transition class.
5. **Accumulator speed?** Refined paired update factors are {quiet:.3f}× quiet,
   {capture:.3f}× capture and {promotion:.3f}× promotion. EP and rights updates
   regress in this micro corpus; all classes and total paths are tabulated.
   The null-heavy mixed average is not a search gain.
6. **Whole engine?** Refined one-million-node factor is
   {one_million['geomean_paired_speedup']:.4f}× {ci(one_million['grouped_bootstrap95'])};
   1000-ms factor is {one_second['geomean_paired_speedup']:.4f}×
   {ci(one_second['grouped_bootstrap95'])}. The former crosses no gain, and
   aggregate timed gains do not remove the fixture/order failures.
7. **Regressions?** {len(new['material_regressions'])} refined and
   {len(old['material_regressions'])} full-sort material fixture/control medians;
   all are enumerated rather than hidden by an aggregate.
8. **Exact correctness?** All required sorting, accumulator/head, fixed-work and
   interruption/restoration gates pass. No arithmetic order changed.
9. **Accept refined sort?** **{status}.**
   {'Retain it only as an isolated experiment; active promotion still requires approval.' if status=='ACCEPTED' else 'Keep Stage 1 as the accepted fallback; do not promote the refinement.'}
10. **Next opportunity?** The unchanged float head remains the largest named
    cost in the verified Stage 1 sample (~32.37%; historical sampling, not a new
    post-refinement profile). A separately authorized dense-head/code-generation
    investigation has a larger measured target than additional tiny-sort tuning.
    No Stage 3, lazy updates, network changes or broader rewrite began here.

## Preservation, artifacts and reproduction

**{preserved['checked_files']}/{preserved['checked_files']} protected files unchanged.**
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
'''
for path in [p.REPO/'NNUE_STAGE2_1_OPTIMIZATION_REPORT.md',p.ROOT/'NNUE_STAGE2_1_OPTIMIZATION_REPORT.md']:
    path.write_text(text,encoding='utf-8')
print('Wrote report:',status,len(text.split()),'words')
