"""Rules/PGN audit, paired-opening statistics and practical finalist handoff."""
from __future__ import annotations
import collections
import csv
import io
import json
import math
import random
import statistics as s
from pathlib import Path
import tournament as t


def interval(values, draws=50000):
    rng=random.Random(2026101780)
    result=sorted(s.mean(rng.choices(values,k=len(values))) for _ in range(draws))
    return [result[int(.025*draws)],result[int(.975*draws)]]


def elo(p):
    return '-infinity' if p<=0 else '+infinity' if p>=1 else -400*math.log10(1/p-1)


def display_elo(value):
    return value if isinstance(value,str) else f'{value:+.1f}'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])+'\n\n'


def finalize():
    config=t.config_check()
    rows=t.completed()
    expected=t.load('schedule.json')
    assert len(rows)==80,'Tournament incomplete: do not invent a finalist; inspect progress.json'
    assert {r['game']['id'] for r in rows}=={g['id'] for g in expected}
    for r in rows:
        t.validate_record(r)
        parsed=t.chess.pgn.read_game(io.StringIO((t.ROOT/'games'/(r['game']['id']+'.pgn')).read_text(encoding='utf-8')))
        assert not parsed.errors and parsed.headers['Result']==r['result']
        assert parsed.end().board().fen()==r['final_fen']
        assert parsed.headers['ThinkTimeMs']=='500'
        assert len(list(parsed.mainline_moves()))==len(t.load('opening-suite.json')[r['game']['opening']]['moves'])+len(r['searches'])
        for label in t.LABELS:
            log=(t.ROOT/'logs'/r['game']['id']/(label+'.log')).read_text(encoding='utf-8')
            commands=[line.split(' > ',1)[1] for line in log.splitlines() if ' > go ' in line]
            assert all(line=='go movetime 500' for line in commands)
    for label in t.LABELS:
        assert sum(r['game']['white']==label for r in rows)==sum(r['game']['black']==label for r in rows)==40
    points=[]
    suite=t.load('opening-suite.json')
    for opening in suite:
        pair=[r for r in rows if r['game']['opening_id']==opening['id']]
        assert len(pair)==2 and pair[0]['game']['white']==pair[1]['game']['black']
        points.append(s.mean(t.core.points(r,t.LABELS[1]) for r in pair))
    score=s.mean(points)
    limits=interval(points)
    summary={}
    all_moves=[dict(game_id=r['game']['id'],opening_id=r['game']['opening_id'],**m) for r in rows for m in r['searches']]
    for label in t.LABELS:
        games=[r for r in rows if label in r['game']['pair']]
        moves=[m for m in all_moves if m['engine']==label]
        stats=t.core.stats(games,label)
        stats.update(median_nodes=s.median(m['nodes'] for m in moves),median_nps=s.median(m['nps'] for m in moves),
                     median_wall_nps=s.median(m['wall_nps'] for m in moves),median_wall_seconds=s.median(m['wall_seconds'] for m in moves),
                     median_reported_seconds=s.median(m['engine_seconds'] for m in moves),median_process_cpu_seconds=s.median(m['process_cpu_seconds'] for m in moves),
                     delays=sum(m['abnormal_delay'] for m in moves),max_engine_seconds=max(m['engine_seconds'] for m in moves),
                     color={color:t.core.stats([r for r in games if r['game'][color]==label],label) for color in ['white','black']})
        summary[label]=stats
    failures=[t.core.load(p) for p in sorted((t.ROOT/'failures').glob('*.json'))]
    delays=sum(m['abnormal_delay'] for m in all_moves)
    fraction=delays/len(all_moves)
    nominal_ok=all(m['wall_seconds']<=.7 and m['engine_seconds']<=.7 for m in all_moves)
    reliability=not failures and nominal_ok and fraction<=config['acceptable_delay_fraction']
    supported=t.core.load(t.PRIOR/'analysis.json')
    benchmarks={f'{x["mode"]}_{x["budget"]}':x for x in supported['summaries'] if x['suite']=='general' and (x['mode'],x['budget']) in [('nodes',1000000),('time',1000)]}
    throughput_support=all(x['ci95'][0]>1 for x in benchmarks.values()) and len(benchmarks)==2
    convincing=limits[0]>.5 or limits[1]<.5
    if not reliability:
        finalist=None;rule='D';reason='Reliability/time-control investigation required; NO VALID FINALIST'
    elif convincing:
        finalist=t.LABELS[1] if limits[0]>.5 else t.LABELS[0]
        rule='A';reason='Opening-pair-aware95% score interval excludes50%'
    elif throughput_support:
        finalist=t.LABELS[1];rule='C/B' if score==.5 else 'B'
        reason='Inconclusive score; predeclared engineering tiebreak for supported throughput with identical evaluation outputs; not proven higher Elo'
    else:
        finalist=None;rule='D';reason='Engineering tiebreak conditions not met; NO VALID FINALIST'
    family=collections.defaultdict(list)
    for opening,value in zip(suite,points):
        family[opening['family_group']].append(value)
    rng=random.Random(2026101780)
    family_keys=list(family)
    draws=[]
    for _ in range(50000):
        selected=rng.choices(family_keys,k=len(family_keys))
        draws.append(s.mean(x for key in selected for x in family[key]))
    draws.sort()
    family_ci=[draws[1250],draws[48750]]
    analysis=dict(completed_games=80,opening_pairs=40,time_ms=500,stats=summary,
        hiddenclip_score_fraction=score,hiddenclip_pair_score95=limits,hiddenclip_elo_equivalent=elo(score),
        elo_equivalent95=[elo(p) for p in limits],pair_scores=points,family_cluster_sensitivity95=family_ci,
        confidence='50000 paired-opening bootstrap draws, seed2026101780;40 units. Conditional on this fixed opening suite and laptop conditions; no absolute Elo claim.',
        statistically_convincing=convincing,selected=finalist,selection_rule=rule,selection_reason=reason,
        failures=failures,abnormal_delays=delays,abnormal_searches=[m for m in all_moves if m['abnormal_delay']],
        abnormal_delay_fraction=fraction,nominal_time_policy_pass=nominal_ok,
        average_searched_plies=s.mean(len(r['searches']) for r in rows),
        average_total_plies=s.mean(len(r['searches'])+len(suite[r['game']['opening']]['moves']) for r in rows),
        cap_adjudications=sum(r['termination']=='adjudicated_maximum_ply_draw' for r in rows),
        resumptions=sum(r['resumptions'] for r in rows),throughput_support=benchmarks,
        preserved_files=len(t.load('preservation-before.json')))
    for rel,expected_hash in t.load('preservation-before.json').items():
        assert t.core.sha(t.REPO/rel)==expected_hash,rel
    t.save('analysis.json',analysis)
    if finalist:
        entry=config['engines'][finalist]
        handoff=dict(selected_engine=finalist,executable=entry['path'],executable_sha256=entry['sha256'],
            nnue_model_identity=t.load('binary-identities.json'),
            nnue_model=dict(features=780,accumulators=[64,64],hidden=32,output=1,embedded=True,
                checkpoint_sha256='7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264',
                export_sha256='a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3'),
            required_uci_options=config['options'],
            search_configuration={k:config[k] for k in ['threads','affinity_mask','hash_mb','ponder','time_ms']},
            tournament_result={k:analysis[k] for k in ['stats','hiddenclip_score_fraction','hiddenclip_pair_score95','hiddenclip_elo_equivalent','elo_equivalent95']},
            selection_rule=rule,reason=reason,statistically_convincing=convincing,
            unresolved_concerns=['Throughput study Stage3.1 remained formally inconclusive due its frozen background-load gate; positive throughput estimates support only the user-authorized practical tiebreak.','Fixed opening suite and80 games cannot establish precise universal Elo.'],
            production_promoted=False,tournament2_started=False)
    else:
        handoff=dict(selected_engine=None,status='NO VALID FINALIST',selection_rule=rule,reason=reason,production_promoted=False,tournament2_started=False)
    t.save('TOURNAMENT_1_FINALIST.json',handoff)
    t.core.write_record(t.ROOT/'games.pgn','\n'.join((t.ROOT/'games'/(r['game']['id']+'.pgn')).read_text(encoding='utf-8') for r in rows))
    game_fields=['game_id','opening_id','white','black','result','termination','searched_plies','total_plies','elapsed_seconds','thinking_seconds','resumptions']
    with (t.ROOT/'games.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=game_fields);writer.writeheader()
        for r in rows:
            g=r['game'];writer.writerow(dict(game_id=g['id'],opening_id=g['opening_id'],white=g['white'],black=g['black'],
                result=r['result'],termination=r['termination'],searched_plies=len(r['searches']),
                total_plies=len(r['searches'])+len(suite[g['opening']]['moves']),elapsed_seconds=r['elapsed_seconds'],thinking_seconds=r['seconds'],resumptions=r['resumptions']))
    fields=list(all_moves[0])
    with (t.ROOT/'moves.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for move in all_moves:
            writer.writerow({k:json.dumps(value) if isinstance(value,(list,dict)) else value for k,value in move.items()})
    report='# StockBear Tournament 1 — NNUE Stage 1 versus Hiddenclip\n\n'
    report+=f'## Executive result\n\n**Practical finalist: {finalist or "NO VALID FINALIST"}. Rule {rule}.** {reason}.\n\n'
    report+=f'Completed exactly **80 games at 500 ms/move**, 40 opening pairs, reversed colors. Hiddenclip score: **{100*score:.2f}%**, paired-opening 95% interval **[{100*limits[0]:.2f}%, {100*limits[1]:.2f}%]**. Statistically convincing: **{convincing}**. No Tournament 2, deployment, training, labeling, engine edits or cleanup occurred.\n\n'
    report+='## Engine and model identities\n\n'+table(['Competitor','EXE SHA256','Kernel'],[(label,config['engines'][label]['sha256'],'clip') for label in t.LABELS])
    report+='Both exact preserved EXEs embed the same780-feature dual64/32 model. Checkpoint SHA256 `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`; export `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`. Original build manifests, identical generated headers, and source comparison establish only `stage1_head.hpp` differs. Live UCI evaluation probes verify evaluator,model,width,hidden andclip kernel. See `provenance.json`, `binary-identities.json`, `preflight.json`. No rebuild occurred.\n\n'
    report+='## Frozen design and preflight\n\n`opening-suite.json`, `schedule.json`, `tournament-config.json` were frozen before official games, seed2026101780. Established main lines reuse24 prior verified sequences plus16 independently specified named sequences. No evaluator/outcome selection. Both get full starting-position history, identical switches,16MiB hash, one thread,CPU0,no pondering. Fresh processes/TT per game; TT retained within game. Pairs alternate which implementation is White first. Both play40White/40Black.\n\n'
    report+='Preflight verified identities, UCI/readiness, explicit `go movetime 500`, legal PV/moves, fixed-node parity, all 40 histories, draw/checkmate rules, color reversal, PGN parsing and atomic checkpoint reconstruction. Two bounded near-mate smoke games were excluded. A third bounded harness game deliberately stopped after two real searches, resumed without replaying them, and ended at a four-search smoke-only safeguard; it is also excluded. All three smoke games remain under `smoke/`, outside official results. New-game initialization and `game` tokens reset TT; partial resumes reconstruct all saved moves and reset both processes, with restarts recorded.\n\n'
    report+='Rules use python-chess including claimable threefold/50-move draws. No evaluation-based adjudication. At400 searched plies beyond the book, a safeguard draw is explicitly adjudicated and counted separately. Crashes, illegal moves,protocol failures/timeouts halt unscored with full logs; saved completed games are never replayed.\n\n'
    report+='## Results\n\n'+table(['Engine','Wins','Draws','Losses','Points /80','Score%'],[(label,summary[label]['wins'],summary[label]['draws'],summary[label]['losses'],summary[label]['points'],f"{100*summary[label]['score_fraction']:.2f}") for label in t.LABELS])
    report+=table(['Engine / color','Games','W/D/L','Points','Score%'],[(label+' / '+color,stats['games'],f"{stats['wins']}/{stats['draws']}/{stats['losses']}",stats['points'],f"{100*stats['score_fraction']:.2f}") for label in t.LABELS for color,stats in summary[label]['color'].items()])
    report+=f'Average searched length {analysis["average_searched_plies"]:.2f} plies; including opening {analysis["average_total_plies"]:.2f}. Maximum-ply adjudications: {analysis["cap_adjudications"]}. Resumed partial-game sessions: {analysis["resumptions"]}.\n\n'
    report+='## Opening-pair uncertainty and Elo-equivalent\n\n'
    report+=f'Bootstrap 40 complete color-reversed opening units, 50,000 draws. Hiddenclip minus Stage 1 Elo-equivalent point **{display_elo(elo(score))}**, 95% interval **[{display_elo(elo(limits[0]))}, {display_elo(elo(limits[1]))}]**. Formula: `-400 * log10(1/p - 1)`. This transforms the observed score; it is neither an absolute rating nor a precise universal Elo difference. Stage 1 score 95% is [{100*(1-limits[1]):.2f}%, {100*(1-limits[0]):.2f}%]. If the score interval contains 50%, superiority is not established. Family-cluster sensitivity score 95%: [{100*family_ci[0]:.2f}%, {100*family_ci[1]:.2f}%]; this secondary check recognizes related opening families and does not pool historical games.\n\n'
    report+='## Search performance and timing\n\n'+table(['Engine','Median nodes','Median reportedNPS','Median wallNPS','Median depth','Median wall /engine seconds','Median CPU seconds'],[(label,summary[label]['median_nodes'],round(summary[label]['median_nps']),round(summary[label]['median_wall_nps']),summary[label]['median_depth'],f"{summary[label]['median_wall_seconds']:.6f} /{summary[label]['median_reported_seconds']:.6f}",summary[label]['median_process_cpu_seconds']) for label in t.LABELS])
    report+='These are descriptive medians on each engine\'s actual tournament positions. Different games/moves reach different positions and depths; these unpaired search samples do not constitute a matched-position causal NPS/depth benchmark. The previous exact-work studies supply the controlled throughput evidence. Higher NPS does not guarantee higher playing strength.\n\n'
    report+=f'Nominal 500 ms each, symmetric 200 ms protocol/OS tolerance: hard ceiling 700 ms; flags above 550 ms wall or 525 ms reported. Abnormal delays {delays}/{len(all_moves)} ({100*fraction:.3f}%). Hard timing policy passed: {nominal_ok}. Engineering-tiebreak delay limit 1%.\n\n'+table(['Engine','Maximum wall','Maximum reported','Abnormal flags'],[(label,f"{summary[label]['max_wall_seconds']:.6f}",f"{summary[label]['max_engine_seconds']:.6f}",summary[label]['delays']) for label in t.LABELS])
    if analysis['abnormal_searches']:
        report+='Flagged searches were retained:\n\n'+table(['Game / searched ply','Engine','Reported ms','Wall ms','CPU ms'],
            [(m['game_id']+' / '+str(m['ply']),m['engine'],f"{1000*m['engine_seconds']:.1f}",f"{1000*m['wall_seconds']:.1f}",f"{1000*m['process_cpu_seconds']:.1f}") for m in analysis['abnormal_searches']])
        report+='The warning is within the frozen tolerance. Both engines received `go movetime 500`; CPU accounting is quantized and does not establish why the stop check/report was late. No cause or extra usable thinking-time advantage is inferred.\n\n'
    report+=f'Game/engine failures recorded: **{len(failures)}**. Full engine transcripts live under `logs/`, game failures under `failures/` if present; complete per-move CPU/wall/time/nodes/depth/score/PV/counters/background activity is in game JSON and moves CSV. Minor protocol overhead is not additional nominal thinking time.\n\n'
    report+='A report-module import collision occurred **after all 80 official games finished**: a transitive Python path change selected the earlier Stage 3 `analyze` module. Reporting was repaired to invoke this workspace\'s script by its explicit path. `provenance/executed-tournament.py` preserves the exact frozen runner used for the games; `harness-recovery.json` records original/repaired hashes. The repair changed only postprocessing dispatch/completed-run handling. No game, engine, model, opening, clock, statistical estimator or selection rule changed, and no game was replayed. This resolved harness issue is separate from engine stability.\n\n'
    report+='## Environment and integrity\n\nAC and unchanged Windows power plan were checked before/after every game. All searches use inheritedCPU0 affinity, verified per move. No priority,power,NitroSense,security or unrelated-app changes. Quiet/Eco is last user-confirmed, not independently measured. Process CPU accounting and system/background deltas are diagnostic, can be quantized, and do not measure actual frequency/temperature/throttling. Games ran serially without concurrent heavy experiments.\n\n'
    report+=f'All **{analysis["preserved_files"]} protected files unchanged**. Exactly80 unique scheduled gameIDs,40 reversed opening pairs,40White/40Black each,full legal replay and parseable individual/aggregatePGNs were checked. No original executable,model,production source or earlier study changed; no cleanup or Tournament2 occurred.\n\n'
    report+='## Explicit conclusions and handoff\n\n'
    leader='NNUE_HIDDENCLIP' if score>.5 else 'NNUE_STAGE1' if score<.5 else 'Neither: equal scores'
    report+=f'1. **Higher score:** {leader}; hiddenclip {summary[t.LABELS[1]]["points"]}/80 versus Stage 1 {summary[t.LABELS[0]]["points"]}/80.\n'
    report+=f'2. **Win/draw/loss totals:** hiddenclip {summary[t.LABELS[1]]["wins"]}/{summary[t.LABELS[1]]["draws"]}/{summary[t.LABELS[1]]["losses"]}; Stage 1 {summary[t.LABELS[0]]["wins"]}/{summary[t.LABELS[0]]["draws"]}/{summary[t.LABELS[0]]["losses"]}.\n'
    report+=f'3. **Score percentages:** hiddenclip {100*score:.2f}%; Stage 1 {100*(1-score):.2f}%.\n'
    report+=f'4. **Statistically convincing:** {convincing}; paired-opening score 95% [{100*limits[0]:.2f}%, {100*limits[1]:.2f}%].\n'
    node_ratio=summary[t.LABELS[1]]['median_nodes']/summary[t.LABELS[0]]['median_nodes']
    report+=f'5. **Nodes at equal nominal time:** hiddenclip median {summary[t.LABELS[1]]["median_nodes"]:,.0f}, Stage 1 {summary[t.LABELS[0]]["median_nodes"]:,.0f}, a descriptive difference of {100*(node_ratio-1):.2f}%. Positions differ; this is not a matched-position effect estimate.\n'
    report+=f'6. **Completed depth:** median {summary[t.LABELS[0]]["median_depth"]}/{summary[t.LABELS[1]]["median_depth"]} for Stage 1/hiddenclip; means {summary[t.LABELS[0]]["mean_depth"]:.3f}/{summary[t.LABELS[1]]["mean_depth"]:.3f}. No higher median depth is demonstrated.\n'
    report+=f'7. **Timing/stability:** {len(failures)} game/engine failures, {delays} minor delay warning(s), hard-policy pass {nominal_ok}.\n'
    report+='8. **Playing-strength gain:** '+('supported conditionally by this paired suite, with uncertain magnitude.' if convincing else 'not established; throughput improvement is separate evidence.')+'\n'
    report+=f'9. **Advance:** {finalist or "NO VALID FINALIST"}, rule {rule}.\n'
    report+='10. **Confidence:** '+('conditional on this opening suite and hardware; the Elo-equivalent interval remains the relevant uncertainty.' if convincing else 'the practical engineering tiebreak is supported; higher Elo is unproven. A fixed 80-game suite cannot establish a precise universal strength difference.')+'\n\n'
    report+='`TOURNAMENT_1_FINALIST.json` records the exact path,hash,model,options,search settings,results,selection rule and concerns. Stage3.1\'s throughput estimates were positive but its formal acceptance remained inconclusive because of background-load flags; this tournament\'s explicit user-authorized tiebreak is distinct from promoting an inference benchmark or a production evaluator. Run Tournament2 only under a separate instruction.\n\n'
    report+='## Frozen opening suite\n\n'+table(['ID','Description','SAN'],[(o['id'],o['description'],o['san']) for o in suite])
    report+='## Reproduction\n\nSee `README.md`: standalone start/status/resume commands. JSON game records are authoritative, PGNs/CSVs are validated derived exports; completed records are skipped. `manifest.json` preserves receipt hashes. No further games are scheduled.\n'
    for old,new in {
        'same780-feature dual64/32':'same 780-feature dual-64/32',
        'evaluator,model,width,hidden andclip':'evaluator, model, width, hidden and clip',
        'seed2026101780':'seed 2026101780','reuse24':'reuse 24','plus16':'plus 16',
        'switches,16MiB':'switches, 16 MiB','thread,CPU0,no':'thread, CPU0, no',
        'play40White/40Black':'play 40 games as White and 40 as Black','At400':'At 400',
        'moves,protocol':'moves, protocol','inheritedCPU0':'inherited CPU0',
        'priority,power,NitroSense,security':'priority, power, NitroSense, security',
        'Exactly80':'Exactly 80','gameIDs':'game IDs','pairs,40White/40Black each,full':'pairs, 40 White/40 Black each, full',
        'individual/aggregatePGNs':'individual/aggregate PGNs','executable,model,production':'executable, model, production',
        'path,hash,model,options,search settings,results,selection':'path, hash, model, options, search settings, results, selection',
        'Stage3.1':'Stage 3.1','Tournament2':'Tournament 2','Nominal500':'Nominal 500',
        'score95%':'score 95%','reportedNPS':'reported NPS','wallNPS':'wall NPS'
    }.items():
        report=report.replace(old,new)
    (t.ROOT/'STOCKBEAR_TOURNAMENT_1_REPORT.md').write_text(report,encoding='utf-8')
    aggregate=(t.ROOT/'games.pgn').read_text(encoding='utf-8')
    stream=io.StringIO(aggregate);count=0
    while (game:=t.chess.pgn.read_game(stream)) is not None:
        assert not game.errors;count+=1
    assert count==80
    t.save('validation.json',dict(passed=True,utc=t.core.utc(),games=80,pairs=40,white_black_balanced=True,parseable_pgns=80,protected_files=analysis['preserved_files'],production_unchanged=True,tournament2_started=False,cleanup=False))
    files={}
    for path in sorted(t.ROOT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or 'artifacts' in path.parts or 'run-logs' in path.parts or path.name=='manifest.json':
            continue
        data=path.read_bytes()
        files[path.relative_to(t.ROOT).as_posix()]=dict(bytes=len(data),sha256=t.core.sha(path),lf_sha256=t.core.hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest())
    t.save('manifest.json',dict(utc=t.core.utc(),files=files,config_sha256=t.core.sha(t.ROOT/'tournament-config.json')))
    print(json.dumps(dict(finalist=finalist,rule=rule,hiddenclip_score=score,score95=limits,finished_games=80)),flush=True)


if __name__=='__main__':
    finalize()
