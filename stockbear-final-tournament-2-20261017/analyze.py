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
    assert len(rows)==80,'Tournament incomplete: do not invent a champion; inspect progress.json'
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
    convincing=limits[0]>.5 or limits[1]<.5
    if not reliability:
        finalist=None;rule='D';reason='Critical reliability/time/data gate failed: NO VALID CHAMPION'
    elif limits[0]>.5:
        finalist='NNUE_HIDDENCLIP';rule='A';reason='NNUE opening-pair score95 lower bound exceeds50%'
    elif limits[1]<.5:
        finalist='CLASSICAL';rule='B';reason='Classical opening-pair score95 lower bound exceeds50%'
    else:
        finalist='CLASSICAL';rule='C';reason='Inconclusive result; retain the preserved classical baseline conservatively. This does not prove higher classical Elo'
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
        resumptions=sum(r['resumptions'] for r in rows),
        preserved_files=len(t.load('preservation-before.json')))
    for rel,expected_hash in t.load('preservation-before.json').items():
        assert t.core.sha(t.REPO/rel)==expected_hash,rel
    roots={label:[next(m for m in r['searches']) for r in rows if r['searches'] and r['searches'][0]['engine']==label] for label in t.LABELS}
    ratios=[];depths=[]
    for opening in suite:
        pair=[r for r in rows if r['game']['opening_id']==opening['id']]
        first={r['searches'][0]['engine']:r['searches'][0] for r in pair}
        ratios.append(first['NNUE_HIDDENCLIP']['wall_nps']/first['CLASSICAL']['wall_nps'])
        depths.append(first['NNUE_HIDDENCLIP']['depth']-first['CLASSICAL']['depth'])
    analysis['matched_opening_roots']=dict(pairs=40,nnue_relative_wall_nps_geomean=math.exp(s.mean(math.log(x) for x in ratios)),nnue_minus_classical_mean_depth=s.mean(depths),interpretation='Same opening history/time; different evaluator search trees,exploratory descriptive')
    t.save('analysis.json',analysis)
    entry=config['engines'].get(finalist,{})
    handoff=dict(selected_engine=finalist,status='selected for later consolidation' if finalist else 'NO VALID CHAMPION',
        executable=entry.get('path'),executable_sha256=entry.get('sha256'),evaluator=entry.get('evaluator'),
        nnue_model=t.core.load(t.T1/'TOURNAMENT_1_FINALIST.json')['nnue_model'] if finalist=='NNUE_HIDDENCLIP' else None,
        required_uci_options=entry.get('options'),
        search_configuration={k:config[k] for k in ['threads','affinity_mask','hash_mb','ponder','time_ms']},
        tournament_result={k:analysis[k] for k in ['stats','hiddenclip_score_fraction','hiddenclip_pair_score95','hiddenclip_elo_equivalent','elo_equivalent95']},
        selection_rule=rule,reason=reason,statistically_convincing=convincing,reliability_pass=reliability,
        unresolved_concerns=['Conditional fixed40-opening suite,80 games,one laptop and500ms; cannot resolve small universal Elo differences.',
            'Quiet/Eco last user-confirmed; thermal/effective frequency unavailable.'],production_promoted=False,cleanup_performed=False)
    t.save('STOCKBEAR_FINAL_CHAMPION.json',handoff)
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
    report='# StockBear Grand Final — NNUE Hiddenclip versus Classical\n\n'
    report+=f'## Executive summary\n\n**Selected configuration: {finalist or "NO VALID CHAMPION"}, Rule {rule}.** {reason}. Exactly80 official games at500ms,40 reversed opening pairs. NNUE score **{100*score:.2f}%**, paired95% **[{100*limits[0]:.2f}%, {100*limits[1]:.2f}%]**. No deployment or default change.\n\n'
    report+='## Exact engine identities and provenance\n\n'+table(['Engine','Executable','SHA256','Evaluator'],[(label,config['engines'][label]['path'],config['engines'][label]['sha256'],config['engines'][label]['evaluator']) for label in t.LABELS])
    report+='The classical EXE is the exact archived prior final-showdown baseline, matching its original64/32 source binary and build receipt. Its embedded NNUE is unused: every classical search must have zero NNUE evaluations. All search sources/headers, classical evaluator, rules and build flags match. Only the NNUE head implementation and clip UCI selector differ; see provenance.json. No rebuild. Hiddenclip is the exact Tournament1 finalist, clip kernel, incremental float32,780 features→dual64→32→1. Checkpoint SHA256 `7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264`; export `a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3`.\n\n'
    report+='## Setup, frozen openings and preflight\n\n'
    report+=f'Tournament1 opening-suite.json was copied byte-for-byte: SHA256 `{config["openings_sha256"]}`. All40 IDs, full legal startpos histories, FENs and moves are unchanged. The80 assignments preserve its balanced order with CLASSICAL replacing Stage1; each competitor plays40White/40Black. Seed2026101780. No outcome-dependent selection, extension or pooling.\n\n'
    report+='Both use go movetime500,16MiB hash,one search thread,no pondering,verified CPU0 affinity; equal search switches. Classical uses Evaluator=classical and supported scalar selector (NNUE unused); challenger uses the exact Tournament1 options Evaluator=nnue, NNUEKernel=clip. Fresh processes/TT each game, retained within game; full history every play. Preflight covers exact hashes/model, legal histories, evaluator counters, clocks,UCI resets,mate/draw rules,PGNs,atomic checkpoints and genuine interrupted/resumed smoke. All smoke results are excluded. Standalone launcher guards duplicate writers and reconstructs partial games without replaying saved moves.\n\n'
    report+='python-chess is authoritative, including claimable repetition/50-move draws and terminal/material rules. No evaluation adjudication;400 searched plies beyond opening is a separately identified safeguard draw. Crashes,illegal moves,protocol failures/timeouts halt unscored with checkpoints and full logs, symmetric for both engines.\n\n'
    report+='## Complete results\n\n'+table(['Engine','Wins','Draws','Losses','Points /80','Score%'],[(label,summary[label]['wins'],summary[label]['draws'],summary[label]['losses'],summary[label]['points'],f"{100*summary[label]['score_fraction']:.2f}") for label in t.LABELS])
    report+=table(['Engine /color','Games','W/D/L','Points','Score%'],[(label+' / '+color,stats['games'],f"{stats['wins']}/{stats['draws']}/{stats['losses']}",stats['points'],f"{100*stats['score_fraction']:.2f}") for label in t.LABELS for color,stats in summary[label]['color'].items()])
    report+=f'Average game length: {analysis["average_total_plies"]:.2f} total plies ({analysis["average_searched_plies"]:.2f} searched); safeguard draws {analysis["cap_adjudications"]}; official partial resumptions {analysis["resumptions"]}. Full80 rows: games.csv and games.pgn.\n\n'
    report+='## Paired uncertainty and Elo-equivalent\n\n'
    report+=f'Frozen Tournament1 method:50,000 bootstrap resamples of40 complete color-reversed opening pairs,seed2026101780. NNUE score {100*score:.2f}% [95% {100*limits[0]:.2f}%,{100*limits[1]:.2f}%]; classical {100*(1-score):.2f}% [95% {100*(1-limits[1]):.2f}%,{100*(1-limits[0]):.2f}%]. NNUE-minus-classical Elo-equivalent **{display_elo(elo(score))} [95% {display_elo(elo(limits[0]))},{display_elo(elo(limits[1]))}]**. Formula -400*log10(1/p-1); boundary scores yield infinities. Convincing superiority: **{convincing}** (interval excludes50%). Opening-family cluster sensitivity NNUE95% [{100*family_ci[0]:.2f}%,{100*family_ci[1]:.2f}%]. This conditional bootstrap is neither an absolute rating nor a guarantee across all chess; family dependence and selected suite remain limitations.\n\n'
    report+='## Search performance\n\n'+table(['Engine','Mean /median depth','Median nodes','Median NPS','Median wall NPS','Median wall /reported ms','Median CPU ms'],[(label,f"{summary[label]['mean_depth']:.3f} /{summary[label]['median_depth']}",summary[label]['median_nodes'],round(summary[label]['median_nps']),round(summary[label]['median_wall_nps']),f"{1000*summary[label]['median_wall_seconds']:.3f} /{1000*summary[label]['median_reported_seconds']:.3f}",1000*summary[label]['median_process_cpu_seconds']) for label in t.LABELS])
    report+='Tournament medians describe different reached positions and search trees; they are not a matched-work inference benchmark or proof of causation. NPS is not chess strength. First searched moves in each opening pair do share identical opening histories and fresh state; root comparisons in analysis.json are exploratory throughput descriptions under different evaluators.\n\n'
    report+='## Timing, reliability and environment\n\n'
    report+=f'Each search requests500ms, symmetric200ms OS/protocol allowance;700ms hard ceiling. Flags at>550ms wall or>525ms reported. Hard-policy pass {nominal_ok}; abnormal flags {delays}/{len(all_moves)} ({100*fraction:.3f}%,frozen1% acceptance limit). Engine/game failures {len(failures)}. Full per-move logs/counters/PVs,CPUtime,walltime and background deltas retained. Protocol-delay proxy is max(0,wall-reported), not a separately measured transport latency.\n\n'
    report+=table(['Engine','Max wall ms','Max reported ms','Warnings'],[(label,f"{1000*summary[label]['max_wall_seconds']:.3f}",f"{1000*summary[label]['max_engine_seconds']:.3f}",summary[label]['delays']) for label in t.LABELS])
    if analysis['abnormal_searches']:
        report+=table(['Game /searched ply','Engine','Wall ms','Reported ms'],[(m['game_id']+' /'+str(m['ply']),m['engine'],f"{1000*m['wall_seconds']:.3f}",f"{1000*m['engine_seconds']:.3f}") for m in analysis['abnormal_searches']])
    report+='AC and the unchanged Windows power plan were checked before/after each game. CPU0 verified per search; no priority,NitroSense,power,security or unrelated-app settings changed. Quiet/Eco is last user-confirmed and not independently measurable here. CPU accounting is quantized (historically15.625ms); system/background deltas do not measure CPU0 contention. Effective frequency,temperature and thermal throttling unavailable; no inferred thermal cause.\n\n'
    report+='## Historical context and final selection\n\nTournament1 compared two implementations of the same model: hiddenclip32wins,Stage1 28wins,20draws,52.50%,+17.4 Elo-equivalent,statistically inconclusive; hiddenclip advanced under its engineering RuleB. This tournament compares learned against handcrafted evaluation. Neither tournament is pooled. The older48-game1second study used unoptimized scalar NNUE and a different suite: classical13/24 against64/32 and17.5/24 against128/32; it is historical context only. Stage1 was accepted as isolated inference optimization; Stage3.1 showed positive throughput with formal environmental inconclusiveness. Those speed findings do not predetermine this match.\n\n'
    report+=f'**Rule {rule}: {finalist or "NO VALID CHAMPION"}.** {reason}. This is a handoff for later explicitly authorized consolidation; no production promotion.\n\n'
    report+='## Answers and interpretation\n\n'
    answers=[f'NNUE defeated classical on observed score: {score>.5}; statistically convincing NNUE win: {limits[0]>.5 and reliability}.',
        f"W/D/L NNUE {summary[t.LABELS[1]]['wins']}/{summary[t.LABELS[1]]['draws']}/{summary[t.LABELS[1]]['losses']}; classical {summary[t.LABELS[0]]['wins']}/{summary[t.LABELS[0]]['draws']}/{summary[t.LABELS[0]]['losses']}.",
        f'Score NNUE {100*score:.2f}%,classical {100*(1-score):.2f}%.',f'Statistically convincing: {convincing}; use the paired interval above.',
        f'NNUE-minus-classical estimated Elo-equivalent {display_elo(elo(score))},uncertainty above.',
        f"Mean completed depth NNUE {summary[t.LABELS[1]]['mean_depth']:.3f},classical {summary[t.LABELS[0]]['mean_depth']:.3f}.",
        f"Median NPS NNUE {summary[t.LABELS[1]]['median_nps']:,.0f},classical {summary[t.LABELS[0]]['median_nps']:,.0f}; descriptive different-tree workloads.",
        f'Engine failures {len(failures)}; every scored move and PV legally replayed.',f'Symmetric500ms requests and700ms ceiling; hard-policy pass {nominal_ok}.',
        f'Selected final configuration {finalist or "NO VALID CHAMPION"},Rule{rule}; not deployed.',
        'Limits:80 games,40 fixed pairs,one laptop,one time budget,related openings and environmental uncertainty; small Elo effects unresolved.',
        ('NNUE has earned a conditional playing-strength win here; independent broader validation remains useful.' if limits[0]>.5 and reliability else 'This NNUE has not demonstrated the required convincing improvement; speed optimization alone is insufficient evidence to replace classical. This does not establish that NNUE approaches cannot improve StockBear.')]
    report+='\n'.join(f'{i}. {v}' for i,v in enumerate(answers,1))+'\n\n'
    report+=f'## Integrity and reproduction\n\nExactly80 unique scheduled games,40 reversed pairs,40White/40Black each; all PGNs legal and results matched. {analysis["preserved_files"]} protected files unchanged. No training,labeling,source/model/default change,cleanup or deployment occurred. See final-audit.json for independently checked exports and manifest.json for checksums. README.md gives start/status/resume/analyze commands; all original studies and raw records retained. No extra games or optimization follow.\n\n'
    report+='## Frozen opening suite\n\n'+table(['ID','Description','SAN'],[(o['id'],o['description'],o['san']) for o in suite])
    (t.ROOT/'STOCKBEAR_GRAND_FINAL_REPORT.md').write_text(report,encoding='utf-8')
    aggregate=(t.ROOT/'games.pgn').read_text(encoding='utf-8')
    stream=io.StringIO(aggregate);count=0
    while (game:=t.chess.pgn.read_game(stream)) is not None:
        assert not game.errors;count+=1
    assert count==80
    t.save('validation.json',dict(passed=True,utc=t.core.utc(),games=80,pairs=40,white_black_balanced=True,parseable_pgns=80,protected_files=analysis['preserved_files'],production_unchanged=True,production_promoted=False,cleanup=False))
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
