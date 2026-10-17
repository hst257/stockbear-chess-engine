"""Render the completed independent validation report from its receipts."""
import statistics as s
import validate as v


def f(x):
    return f'{x:.4f}'


def ci(xs):
    return f'[{f(xs[0])}, {f(xs[1])}]'


def control(mode, budget):
    return f'{budget:,} nodes' if mode=='nodes' else f'{budget} ms'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n\n'


def main():
    a=v.load('analysis.json')
    lookup={(x['suite'],x['mode'],x['budget']):x for x in a['summaries']}
    sentinel=lookup[('sentinel','time',100)]
    general_sentinel=next(x for x in a['per_position'] if (x['suite'],x['position'],x['mode'],x['budget'])==('general','piece_endgame','time',100))
    eg=lookup[('endgame','time',100)]
    long=[lookup[('general','nodes',1000000)],lookup[('general','time',1000)]]
    identity=v.load('binary-identities.json')
    env=a['environment']
    preserved=v.load('preservation-after.json')
    report='# StockBear — Stage 3.1 independent hidden-clipping validation\n\n'
    report+='## Executive decision\n\n'
    report+=f'**{a["decision"]}.** '
    if a['decision']=='ACCEPTED':
        report+='The unchanged Stage 3 `hiddenclip` executable is supported as the new **experimental NNUE baseline**. Stage 1 remains the preserved fallback. '
    elif a['decision']=='REJECTED':
        report+='Do not replace Stage 1 as the experimental baseline; the predeclared rejection gates are identified below. '
    else:
        report+='Retain Stage 1 as the accepted experimental baseline; the incomplete acceptance gates are identified below. '
    report+='The active engine, production source, weights, search policy and classical default are unchanged. No production promotion is authorized by this study.\n\n'
    failed=[name for name,passed in a['gates'].items() if not passed]
    report+='Failed acceptance gates: '+(', '.join(f'`{name}`' for name in failed) if failed else 'none')+'. '
    if failed==['environmental_flags_within_budget']:
        report+='**Every numerical, fixed-work, regression, order and dependence gate passes.** Formal acceptance is withheld solely because the frozen environmental limit was exceeded: '+f'{env["flagged_blocks"]}/{env["block_count"]} blocks ({100*env["flag_fraction"]:.1f}%) were flagged, versus the predeclared 25% maximum. This is neither a demonstrated hiddenclip defect nor permission to relax the threshold after seeing favorable results.'
    report+='\n\n'
    report+=f'Fresh general-suite factors: **{f(long[0]["factor"])}×** at 1M nodes {ci(long[0]["ci95"])} and **{f(long[1]["factor"])}×** at 1000 ms {ci(long[1]["ci95"])}. '
    report+=f'The separately repeated original 100-ms sentinel gives **{f(sentinel["factor"])}×**, repeat-only 95% {ci(sentinel["ci95"])}. Independent endgames at 100 ms give **{f(eg["factor"])}×**, grouped 95% {ci(eg["ci95"])}.\n\n'
    report+=f'The frozen schedule completed **{a["search_count"]:,} searches / {a["search_count"]//2:,} pairs**, serially, in {env["elapsed_seconds"]/60:.1f} minutes including warm-up, block probes and pauses. No tournaments, training, labeling, sealed-test access, rebuilds, new optimization variants or additional primary repetitions occurred. This validation is published in one final commit.\n\n'
    report+='## Exact executable, model and build provenance\n\n'
    report+=table(['Artifact','SHA-256'],[(path,digest) for path,digest in identity['files'].items()])
    report+='Both EXEs/PDBs match the original Stage 3 manifest. They resolve the same system CRT API-set/kernel imports; no local runtime replacement is involved. `build-provenance.json` preserves the original compiler commands, source hashes and current shared OS runtime hashes. Model weights are **embedded from identical frozen generated headers**, matching the archived export/checkpoint; these binaries do not dynamically load a newly supplied export.\n\n'
    report+='Baseline provenance: Stage 1 `f397a5af002900bbc15a7261dc6027c48daaeff4`; validation branch starts from Stage 3 `3aaaf5046993c154793845a4e865d9fd51832dec`. Zig 0.13 / Clang 18.1.6, C++17, `-O2 -pthread -Wall -Wextra -ffp-contract=off`, compact strategy 2. No fast-math, reassociation, FMA contraction or new build was introduced. Hiddenclip preserves dense/input arithmetic and sequential output reduction, replacing only hidden clipping with the existing vector clipping semantics.\n\n'
    report+='## Frozen plan and workload\n\n'
    report+=f'`validation-plan.json` was frozen at {v.load("validation-plan.json")["frozen_utc"]}, before performance pairs. Seed **2026101731**; `schedule.json` fixes all 276 blocks and pair orders. Ten paired repeats on the unchanged original 12 positions use 200k/1M nodes and 100/500/1000 ms. Twelve paired repeats on 12 independent composed endgames use those controls plus 200 ms. A separate 12-repeat sentinel receives all six focused controls. Every fixture/control has exactly balanced engine order. Position/control blocks are randomized within repeat rounds. General and focused sentinel observations are reported separately, never pooled.\n\n'
    report+='Both EXEs use CPU0 affinity, one search thread, 16 MiB hash, `NNUEKernel=clip`, identical frozen search switches, no pondering, complete supplied histories and a fresh TT (`game=object()`) per search. Identical 25k-node warm-ups precede primary collection and are excluded. The 30–45-minute estimate and 90-minute benchmark cap were fixed before timing.\n\n'
    report+=table(['Independent group / fixture','Coverage','Legal moves','Check','Captures'],
        [(r['group']+' / '+r['id'],r['category'],r['legal_moves'],r['in_check'],r['legal_captures']) for r in v.load('endgame-positions.json')])
    report+='These are legal, nonterminal, hand-composed coverage fixtures, not game/dataset samples, candidate-selected variations, or sealed positions. No multiple positions from one game are counted as independent. Similar material templates can still correlate: intervals describe this convenience suite, not a random population of chess endgames. Full FENs/origins are in the frozen position manifests.\n\n'
    report+='## Environmental controls and telemetry\n\n'
    report+=f'AC power and the OEM Acer plan were checked before and after **all {env["block_count"]} blocks**; all checks passed. CPU0 affinity was verified for every child search. Quiet/Eco is the last user-confirmed NitroSense preference; the current OEM mode is not independently exposed. No power, CPU priority, application, security or driver setting was changed.\n\n'
    report+=f'A 0.5-second pre-block load probe pauses above 20% other CPU use, at most three 5-second pauses per block. Any probe/search above 25% flags the entire block, symmetrically. **All observations remain in the primary analysis.** There were {env["pauses"]} pauses and {env["flagged_blocks"]}/{env["block_count"]} flagged blocks ({100*env["flag_fraction"]:.1f}%). Other CPU percent of total logical capacity: median {env["background"]["median"]:.2f}, range {env["background"]["minimum"]:.2f}–{env["background"]["maximum"]:.2f}. This does not directly measure CPU0 contention.\n\n'
    report+='Process CPU time comes from `GetProcessTimes` around each search; wall time and wall NPS remain primary. Observed CPU deltas are quantized in 15.625-ms increments, and some short-search CPU/wall ratios exceed 1, illustrating accounting resolution/boundary limitations against the high-resolution wall interval. They are not literal CPU utilization readings. CPU accounting includes search/protocol work over the same operation; short-search CPU ratios are diagnostic, not replacements for wall results.\n\n'
    telemetry=env['cpu0_telemetry']
    report+=f'An additional **{telemetry["samples"]} CPU0 Windows counter snapshots** ({telemetry["errors"]} errors) cover {telemetry["search_records_with_nearby_snapshot"]}/{a["search_count"]} searches within ±10 seconds. Collection began partway through the schedule. Raw timestamps/offsets remain in CSV/JSON; missing samples are explicit. '
    report+='The Windows counter interface is documented by [Microsoft](https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters). `ProcessorFrequency` is not accepted as measured effective MHz; `% Processor Performance` and limit flags are retained as reported diagnostics without an independently calibrated clock conversion. Reliable effective search-core MHz, temperature and thermal-throttling measurements remain unavailable. No thermal or frequency cause is established from these counters.\n\n'
    comparison=env.get('before_after_counter_start',{})
    if comparison:
        report+=f'CIM query wall duration: median {telemetry["query_seconds"]["median"]:.3f}s, maximum {telemetry["query_seconds"]["maximum"]:.3f}s. Flagged fractions were {100*comparison["before"]["flagged_fraction"]:.1f}% across {comparison["before"]["blocks"]} blocks before counter collection, versus {100*comparison["after"]["flagged_fraction"]:.1f}% across {comparison["after"]["blocks"]} afterward. These unequal windows are diagnostic only; they neither establish nor rule out observer overhead. Short system-CPU deltas also have accounting/interval limitations. A separate three-second process snapshot is preserved in `environment-system-snapshot.json`; it cannot explain all transient flags. No application or thermal cause is inferred.\n\n'
    report+=table(['Reported CPU0 counter','Median','Range'],[(k,f(x['median']),f"{f(x['minimum'])}–{f(x['maximum'])}") for k,x in telemetry['reported_values'].items() if x])
    report+='`setup-audit.json` discloses pre-measurement fixture/harness corrections and the zero-duration load-probe fix. `discarded.jsonl` preserves one aborted initial first-pair attempt (`0:0`), with **zero captured search records**, caused by that probe error before the first measured search. The subsequent run completed each scheduled pair exactly once; no completed performance measurement was discarded. The plan/position set was not altered after timings began. `events.jsonl` preserves starts/resumes/warm-ups/pauses. No inconvenient performance pair was excluded.\n\n'
    report+='## Statistics and limitations\n\n'
    report+='Primary estimator: `exp(mean(per-position median(log(candidate wall-NPS / baseline wall-NPS))))`. Fixed-node ratios equal inverse elapsed-time ratios because the work is identical. Timed NPS uses **actual total nodes**, including unfinished iterations; reported completed depth/PV can differ without a correctness failure.\n\n'
    report+='The 95% hierarchical bootstrap uses 10,000 draws, resampling position groups and paired repeats within positions. Sentinel intervals resample its repeats only and are explicitly **not across-position confidence intervals**. A separate circular length-two repeat-block bootstrap shares repeat indices across positions to test common temporal shocks. Early/late halves, normalized baseline drift, order subsets, stable-block subsets and leave-one-position-out estimates are sensitivities, not new primary estimators. No old Stage 3 observations enter these estimates. Intervals are unadjusted for multiple comparisons and do not remove systematic scheduling, thermal or frequency bias.\n\n'
    report+='Material means an observed factor below `1/1.03 = 0.970874`, equivalent to >3% additional elapsed time for equal work. For timed searches this is an **equivalent throughput penalty**, not a literal >3% longer time budget. A noisy median alone is not an established defect. The frozen plan distinguishes repeat intervals/consistent controls and orders from isolated short-time noise, and specifies ACCEPTED/REJECTED/INCONCLUSIVE gates before measurement.\n\n'
    for suite,title in [('general','Fresh frozen 12-position suite'),('endgame','Independent endgame suite'),('sentinel','Original piece-endgame sentinel, focused repeats')]:
        report+='## '+title+'\n\n'
        report+=table(['Control','Factor / 95%','CPU-NPS factor','Baseline first / candidate first','Length-2 95%','Stable-block factor'],
            [(control(x['mode'],x['budget']),f"{f(x['factor'])}× {ci(x['ci95'])}",f(x['cpu_factor']),
              f"{f(x['order']['baseline'])} / {f(x['order']['hiddenclip'])}",ci(x['circular_length2_ci95']),
              f(x['stable_block_factor']) if x['stable_block_factor'] else 'unavailable') for x in a['summaries'] if x['suite']==suite])
        if suite=='sentinel':
            report+='**All intervals in this sentinel table are repeat-only.** FEN: `8/5pk1/6p1/3R4/8/5PK1/6P1/1r6 w - - 0 1`.\n\n'
    report+='## Original anomaly and fresh sentinel diagnosis\n\n'
    report+='Historical Stage 3 general factors were 1.0530 / 1.0642 / 1.0566 / 1.0632 / 1.0768 at 200k / 1M / 100 / 500 / 1000 ms. Its seven sentinel100 factors were 0.9285, 0.9132, 1.0613, 1.0490, 1.1960, 0.9300, 0.9050; median 0.9300, repeat-only interval approximately [0.9132, 1.0613]. That unresolved observation motivated this independent study.\n\n'
    focused=next(x for x in a['per_position'] if (x['suite'],x['mode'],x['budget'])==('sentinel','time',100))
    report+=f'Fresh focused 100-ms sentinel: **{f(sentinel["factor"])}× {ci(sentinel["ci95"])}**; order medians {f(focused["order_medians"]["baseline"])} / {f(focused["order_medians"]["hiddenclip"])}. The separately collected general-suite sentinel gives **{f(general_sentinel["factor"])}× {ci(general_sentinel["repeat95"])}**, based on ten repeats. Neither is pooled with the historical seven or with the other fresh set.\n\n'
    report+='Focused 100-ms paired factors, in repeat order: '+', '.join(f(x)+'×' for x in focused['ratios'])+'.\n\n'
    stats=focused['records_summary']
    report+=table(['100-ms focused sentinel','Baseline','Hiddenclip'],[(key,
        f"{f(stats['baseline'][key]['median'])} [{f(stats['baseline'][key]['minimum'])}, {f(stats['baseline'][key]['maximum'])}]",
        f"{f(stats['hiddenclip'][key]['median'])} [{f(stats['hiddenclip'][key]['minimum'])}, {f(stats['hiddenclip'][key]['maximum'])}]")
        for key in ['wall_seconds','seconds','process_cpu_seconds','nodes','depth','seldepth','eval_calls','qnodes']])
    report+=f'Focused sentinel CPU-NPS factor is {f(focused["cpu_factor"])}×; baseline/candidate median CPU/wall utilization fractions are {f(focused["cpu_wall_baseline"]["median"])} / {f(focused["cpu_wall_candidate"]["median"])}. Paired log-ratio correlation with candidate-minus-baseline background load is {focused["load_difference_log_ratio_correlation"]}; lag-one repeat correlation is {focused["lag1_log_ratio_correlation"]}. These are small-sample diagnostics, not causal estimates. Actual node totals, completed depths, iterations and counters are preserved. Timing/depth boundaries and scheduler variation can change timed work; unchanged code alone does not prove which caused the old anomaly.\n\n'
    report+='In the fresh focused 100-ms sentinel, **both engines completed depth 7 in every repetition**, and every engine-reported time was 100 ms. Wall time stayed approximately 102 ms. Thus the new individual losses are variation in actual total node completion, not different completed-depth reports or a large protocol delay. There is no fresh evidence identifying the old depth-boundary or thermal mechanism.\n\n'
    cpu=v.load('cpu-diagnostics.json')
    report+='## CPU-accounting disagreement investigation\n\n'
    report+='A secondary **read-only** analysis was added after observing that the 200k general-suite CPU-NPS point (0.9828×) disagrees in direction with its wall-NPS point (1.0574×). It does not change the predeclared wall estimator, data, thresholds or decision. CPU intervals use the same grouped/nested bootstrap; sentinel intervals remain repeat-only. The sum-based alternative computes each fixture\'s total nodes / total CPU time before taking the across-fixture geometric ratio, reducing division of individual quantized deltas.\n\n'
    report+=table(['Suite / control','Wall factor','CPU factor / diagnostic95','Sum-based CPU-NPS factor'],
        [(r['suite']+' / '+control(r['mode'],r['budget']),f(r['wall_factor']),f"{f(r['cpu_factor'])} {ci(r['cpu_diagnostic95'])}",f(r['summed_cpu_nps_factor'])) for r in cpu['summaries']])
    report+=f'All CPU deltas lie on the observed 15.625-ms grid ({cpu["deltas_not_on_quantum_grid"]} exceptions); {cpu["cpu_wall_above_one"]} short/other searches have CPU/wall >1. The 200k general CPU interval [0.9086, 1.0952] includes both loss and gain, while its sum-based point is 1.0105×. This discrepancy is unresolved at short-control accounting precision; it does **not** establish opposite sustained throughput. The 1M and 1000-ms general CPU intervals are positive and agree with wall results. No CPU statistic replaces the primary result, and CPU/background correlations share accounting inputs rather than proving a causal mechanism.\n\n'
    report+='## Temporal and execution-order sensitivity\n\n'
    report+=table(['Suite / control','First / second half','Normalized baseline round range','Lag-1 ratio correlation'],
        [(x['suite']+' / '+control(x['mode'],x['budget']),f"{f(x['first_half'])} / {f(x['second_half'])}",
          f"{f(min(x['normalized_baseline_round_nps']))}–{f(max(x['normalized_baseline_round_nps']))}",x['lag1_round_log_ratio_correlation'])
         for x in a['summaries']])
    report+=f'Order affects the magnitude at 1000ms: baseline-first {f(long[1]["order"]["baseline"])}× versus candidate-first {f(long[1]["order"]["hiddenclip"])}×; both favor hiddenclip. The 1M order points are nearly equal ({f(long[0]["order"]["baseline"])} / {f(long[0]["order"]["hiddenclip"])}). Stable-block long-control factors remain {f(long[0]["stable_block_factor"])} / {f(long[1]["stable_block_factor"])} across all 12 fixtures, each with {long[0]["stable_block_pairs"]} / {long[1]["stable_block_pairs"]} retained pairs; these subsets do not replace the primary estimates.\n\n'
    report+='Order-specific grouped points are listed above; per-position order medians are in `analysis.json`. Drift and dependence checks do not establish stationary thermal conditions or eliminate correlated laptop noise. Sparse provider counter snapshots cannot explain individual short searches. CPU and wall diagnostics are shown separately rather than silently exchanging the primary metric.\n\n'
    report+='## Fresh correctness and integrity\n\n'
    report+=f'Fresh checks passed on all 24 distinct validation positions at 200k nodes, with exact move/score/PV/depth/seldepth/node/counter and completed-iteration parity. All **{a["fixed_work_pairs"]} primary fixed-node pairs** also match exactly, reaching their requested node budgets. Eight explicit cancellation checks, four post-stop fixed-work reruns and three classical fixed-work pairs passed. Both benchmark EXEs expose identical UCI defaults/options, and all three preserved production UCI executables report classical as default.\n\n'
    report+='The unchanged Stage 3 receipts retain 161,420 head bit comparisons, 4,352 extra special-value comparisons, 31,876 legal / 26,908 null transitions and restoration tests; these historical tests were reused, not needlessly repeated or claimed fresh. `correctness.json` identifies their hashes and records all fresh gates.\n\n'
    report+=f'**{preserved["files"]:,} protected files unchanged**, including source, active executables, models, previous studies, original EXEs/PDBs and generated headers. Exact identities are checked before/after. No candidate rebuild or production alteration occurred.\n\n'
    report+='## Per-position medians and material regressions\n\n'
    for suite in ['general','endgame','sentinel']:
        controls=[x for x in v.CONTROLS if suite!='general' or x!=('time',200)]
        rows=[x for x in a['per_position'] if x['suite']==suite]
        report+='### '+suite.capitalize()+'\n\n'
        report+=table(['Fixture']+[control(*x) for x in controls],[(position,)+tuple(f(next(x['factor'] for x in rows if x['position']==position and (x['mode'],x['budget'])==ctrl)) for ctrl in controls)
                     for position in sorted({x['position'] for x in rows})])
    report+=f'Observed material fixture/control medians: **{len(a["material_medians"])}**; established material regressions: **{len(a["established"])}**; unresolved concerns: **{len(a["unresolved"])}**.\n\n'
    if a['material_medians']:
        report+=table(['Suite / fixture','Control','Factor / repeat95','Equivalent elapsed penalty','Classification'],
            [(r['suite']+' / '+r['position'],control(r['mode'],r['budget']),f"{f(r['factor'])} {ci(r['repeat95'])}",
              f"{r['equivalent_elapsed_percent']:.2f}%",r['classification']) for r in a['material_medians']])
    report+='Worst ten fixture/control medians, including all observed losses:\n\n'
    report+=table(['Suite / fixture','Control','Factor','Repeat-only 95%'],[(r['suite']+' / '+r['position'],control(r['mode'],r['budget']),f(r['factor']),ci(r['repeat95']))
                 for r in sorted(a['per_position'],key=lambda x:x['factor'])[:10]])
    report+='## Predeclared decision gates\n\n'
    report+=table(['Gate','Pass'],list(a['gates'].items()))
    report+='The thresholds were not adjusted to the observed results. Position/control repeat intervals are unadjusted diagnostics; aggregate grouped intervals and consistency/order/environment checks govern the overall conclusion. No majority-of-wins or Elo shortcut was used.\n\n'
    report+='## Explicit answers and recommendation\n\n'
    reproduced='Yes, an established material regression is present.' if any(r['suite']=='sentinel' and r['mode']=='time' and r['budget']==100 for r in a['established']) else ('No: the fresh focused median is positive, with its repeat-only 95% lower bound above 1; the historical 7.53% penalty did not reproduce.' if sentinel['ci95'][0]>1 else 'The historical 7.53% equivalent penalty is not established by the fresh focused repeats; see the median and interval below.')
    answers=[
        ('Was the original 100-ms slowdown reproducible?',reproduced),
        ('Fresh sentinel median and uncertainty?',f"{f(sentinel['factor'])}× {ci(sentinel['ci95'])}, 12 paired repeats, repeat-only interval; fresh general sentinel {f(general_sentinel['factor'])}× {ci(general_sentinel['repeat95'])}, separately reported."),
        ('Independent endgame systematic slowdown?',f"100-ms grouped factor {f(eg['factor'])}× {ci(eg['ci95'])}; noninferiority gate (>0.970874 lower bound): {a['gates']['endgame100_noninferior']}."),
        ('Did the frozen suite reproduce the earlier 6–8% gain?',('Yes, the independent point estimates reproduce that magnitude. ' if all(1.06<=x['factor']<=1.08 for x in long) else 'The exact magnitude differs; see the fresh points and intervals. ')+f"Fresh long-control gains are {100*(long[0]['factor']-1):.2f}% at 1M and {100*(long[1]['factor']-1):.2f}% at 1000 ms. Historical observations are not pooled; formal acceptance remains subject to the environmental gate."),
        ('Fixed-node and timed gains?', 'All five general controls and all six focused controls appear in the separate tables; fixed-node inverse-time factors are equivalent to wall-NPS factors, timed factors use actual nodes.'),
        ('Execution-order sensitivity?',f"General 1M baseline-first/candidate-first {f(long[0]['order']['baseline'])}/{f(long[0]['order']['hiddenclip'])}; 1000ms {f(long[1]['order']['baseline'])}/{f(long[1]['order']['hiddenclip'])}. Both-order positive gate: {a['gates']['long_orders_positive']}."),
        ('Did CPU/frequency explain anomalies?',f"General long-control CPU-NPS points {f(long[0]['cpu_factor'])}/{f(long[1]['cpu_factor'])}, versus wall {f(long[0]['factor'])}/{f(long[1]['factor'])}; both favor hiddenclip in this study. This supports a throughput gain but does not identify the historical cause. No calibrated effective-MHz or thermal attribution is available."),
        ('Were fixed-work results identical?',f"Yes: {a['fixed_work_pairs']} primary fixed-node pairs plus the fresh correctness suite, including completed iterations."),
        ('Any material regressions remaining?',f"{len(a['material_medians'])} observed medians, {len(a['established'])} established, {len(a['unresolved'])} unresolved; all enumerated above."),
        ('Replace Stage 1 as experimental baseline?',f"{a['decision']}: "+('yes for future isolated NNUE experiments, preserve Stage 1 fallback; no production promotion.' if a['decision']=='ACCEPTED' else 'retain Stage 1; no production promotion.')),
        ('Next highest-value opportunity?', 'First resolve the environmental acceptance limitation before replacing the accepted baseline. The unchanged dense matrix multiply remains the largest measured head component (Stage 3 historical profile: 859/1257 head samples, approximately 68%). A separately authorized strict-float dense-kernel/code-generation investigation has the clearest optimization target; preserve operation order and validate whole search. No further validation, Stage 4 or new optimization was started.')]
    report+='\n'.join(f'{i}. **{q}** {answer}' for i,(q,answer) in enumerate(answers,1))+'\n\n'
    report+='## Reproduction and preserved evidence\n\n'
    report+='See workspace `README.md` for exact PowerShell commands. `validation-plan.json`, `schedule.json`, position manifests, `pairs.jsonl`, raw CSV/JSON, per-position CSV, environment/block/CPU telemetry, correctness/provenance receipts and analysis scripts preserve the investigation. `manifest.json` records SHA-256, byte counts and normalized text hashes; original executables/PDBs remain in the preserved Stage 3 artifacts, with byte-identical local archival copies in this workspace\'s ignored `artifacts/exact-binaries/` and `archived-binaries.json` receipts. Reports and measurements from earlier stages are untouched. No additional games, repeats or follow-up automation are scheduled.\n'
    (v.ROOT/'NNUE_STAGE3_1_VALIDATION_REPORT.md').write_text(report,encoding='utf-8')
    (v.REPO/'NNUE_STAGE3_1_VALIDATION_REPORT.md').write_text(report,encoding='utf-8')
    print('Report rendered:',a['decision'])


if __name__=='__main__':
    main()
