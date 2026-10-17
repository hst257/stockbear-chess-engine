"""Standalone frozen 80-game tournament. Never builds or changes an engine."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parent
PRIOR=REPO/'nnue-validation-stage3-1-20261017'
STAGE3=REPO/'nnue-optimization-stage3-20261017'
sys.path[:0]=[str(ROOT),str(REPO),str(PRIOR)]
import chess
import chess.engine
import chess.pgn
from tools import nnue_showdown as core
from tools.profile_nnue_diagnosis import canonical
from tools.nnue_diagnosis import capture
import validate as monitor
import openings

LABELS=('NNUE_STAGE1','NNUE_HIDDENCLIP')


def save(name, value):
    core.save(ROOT/name,value)


def load(name):
    return core.load(ROOT/name)


def event(kind, **kwargs):
    path=ROOT/'events.jsonl'
    with path.open('a',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(dict(event=kind,utc=core.utc(),**kwargs),allow_nan=False)+'\n')
        stream.flush()
        os.fsync(stream.fileno())


def freeze():
    assert not (ROOT/'tournament-config.json').exists(),'Preserve frozen config'
    identities=monitor.identities()
    save('binary-identities.json',identities)
    # Establish that the intended head is the only source difference.
    source={}
    for label in ['baseline','hiddenclip']:
        source[label]={p.name:core.sha(p) for p in (STAGE3/f'artifacts/{label}-source').glob('*') if p.is_file()}
    assert source['baseline'].keys()==source['hiddenclip'].keys()
    difference=[name for name in source['baseline'] if source['baseline'][name]!=source['hiddenclip'][name]]
    assert difference==['stage1_head.hpp'],difference
    original=core.load(PRIOR/'build-provenance.json')
    for label,path in [('baseline',REPO/'nnue-optimization-stage1-20261017/artifacts/generated'),
                       ('hiddenclip',STAGE3/'artifacts/generated')]:
        source[label]['generated']={p.name:core.sha(p) for p in path.glob('*') if p.is_file()}
    assert source['baseline']['generated']==source['hiddenclip']['generated']
    save('provenance.json',dict(source_hashes=source,only_source_difference=difference,
         original_build_receipts=original,model='Embedded identical 780 -> dual64 -> 32 ->1 frozen float weights; no runtime substitution',
         historical_correctness=core.sha(PRIOR/'correctness.json')))
    protected=core.load(PRIOR/'preservation-before.json')
    for rel in core.load(PRIOR/'manifest.json')['files']:
        protected[rel]=core.sha(REPO/rel)
    protected['nnue-validation-stage3-1-20261017/manifest.json']=core.sha(PRIOR/'manifest.json')
    save('preservation-before.json',{rel:core.sha(REPO/rel) for rel in protected})
    suite=openings.make()
    save('opening-suite.json',suite)
    schedule=[]
    for i,opening in enumerate(suite):
        for reverse in range(2):
            white,black=LABELS if (i+reverse)%2==0 else LABELS[::-1]
            schedule.append(dict(id=f'G{len(schedule)+1:03}',opening=i,opening_id=opening['id'],
                                 white=white,black=black,ms=500,pair=list(LABELS)))
    save('schedule.json',schedule)
    options=core.load(STAGE3/'plan.json')['options']
    assert options['Evaluator']=='nnue' and options['NNUEKernel']=='clip'
    engines={label:dict(name=label,path=str(monitor.BINARIES[b]),sha256=core.sha(monitor.BINARIES[b]),
                       kernel='clip',network_sha256=core.load(STAGE3/'plan.json')['network_sha256'],width=64,hidden=32)
             for label,b in zip(LABELS,['baseline','hiddenclip'])}
    config=dict(schema=1,created_utc=core.utc(),seed=2026101780,engines=engines,options=options,
                openings_sha256=core.sha(ROOT/'opening-suite.json'),schedule_sha256=core.sha(ROOT/'schedule.json'),
                games=80,opening_pairs=40,time_ms=500,threads=1,affinity_mask=1,hash_mb=16,ponder=False,
                protocol_allowance_seconds=.2,abnormal_wall_seconds=.55,abnormal_engine_seconds=.525,
                acceptable_delay_fraction=.01,max_searched_plies=400,
                rules=dict(draws='python-chess outcome(claim_draw=True): claimable threefold/50-move plus automatic and terminal rules',
                    cap='400 searched plies beyond opening: explicitly adjudicated draw, never evaluation-based',
                    fresh_state='New processes and TT every game; retain TT within game. Full startpos opening/game history each play. Resume partial games with both fresh engines/TT, record restart; never replay saved moves.',
                    failure='Crash/illegal move/protocol timeout/corrupt output: halt, retain unfinished state and full protocol logs; no automatic forfeit, no silent replay. Resume only incomplete search after investigating. Persistent engine fault -> NO VALID FINALIST.',
                    power='AC and unchanged Acer plan required before/after every game; stop on loss/change; no settings changes',
                    timing='Nominal go movetime500 for both. Wall >0.7s or reported >0.7s is hard failure; >0.55s wall / >0.525s reported flagged, retained; >1% flagged moves blocks engineering tiebreak.',
                    winner='A: paired-opening95 score CI excludes50% -> select convincing leader, absent serious reliability issues. B/C: otherwise hiddenclip if stable/correct/time-acceptable and prior throughput supported. D: persistent correctness/stability problems -> NO VALID FINALIST; never deploy.',
                    statistics='50000-draw opening-pair bootstrap (40 units, two color-reversed games each), seed2026101780; Elo-equivalent transform endpoints incl infinite bounds. Family-cluster sensitivity secondary, not pooled with old games.',
                    limits='Exactly80 official games; smoke excluded; no extensions, Tournament2, cleanup, engine/model/search/default changes'))
    save('tournament-config.json',config)
    save('environment.json',monitor.environment())
    print('Frozen exactly80 games /40 color-reversed opening pairs at500ms',flush=True)


def config_check():
    config=load('tournament-config.json')
    assert core.sha(ROOT/'opening-suite.json')==config['openings_sha256']
    assert core.sha(ROOT/'schedule.json')==config['schedule_sha256']
    assert monitor.identities()==load('binary-identities.json')
    for entry in config['engines'].values():
        assert core.sha(Path(entry['path']))==entry['sha256']
    return config


class LoggedProtocol(core.CapturingProtocol):
    current_log=None

    def __init__(self):
        super().__init__()
        self.log_path=Path(self.current_log)
        self.log_path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=self.log_path.open('a',encoding='utf-8',buffering=1)
        self.stream.write(f'# session {core.utc()}\n')

    def send_line(self,line):
        self.stream.write(core.utc()+' > '+line+'\n')
        super().send_line(line)

    def line_received(self,line):
        self.stream.write(core.utc()+' < '+line+'\n')
        super().line_received(line)

    def connection_lost(self,exc):
        try:
            super().connection_lost(exc)
        finally:
            self.stream.close()


def player(label, game_id, config):
    entry=config['engines'][label]
    LoggedProtocol.current_log=ROOT/'logs'/game_id/(label+'.log')
    engine=chess.engine.SimpleEngine.popen(LoggedProtocol,entry['path'],timeout=10,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert engine.options['Evaluator'].default=='classical'
        engine.configure(config['options'])
        engine.ping()
        actual=core.identity(engine)
        assert all(actual[k]==value for k,value in [('evaluator','nnue'),('kernel','clip'),
                   ('sha256',entry['network_sha256']),('width',64),('hidden',32)]),actual
        assert monitor.affinity(engine.transport.get_pid())==1
        engine.timeout=config['protocol_allowance_seconds']
        return engine
    except BaseException:
        engine.close()
        raise


def board_for(game, searches=()):
    board=chess.Board()
    opening=load('opening-suite.json')[game['opening']]
    for move in opening['moves']:
        board.push_uci(move)
    assert board.fen()==opening['fen']
    for row in searches:
        assert row['engine']==game['white' if board.turn else 'black']
        assert row['side']==('white' if board.turn else 'black')
        board.push_uci(row['move'])
    return board


def outcome(board, searches, config):
    result=board.outcome(claim_draw=True)
    if result:
        return result.result(),result.termination.name.lower()
    if len(searches)>=config['max_searched_plies']:
        return '1/2-1/2','adjudicated_maximum_ply_draw'
    return None,None


def pgn_text(record):
    game=record['game']
    board=board_for(game,record['searches'])
    pgn=chess.pgn.Game.from_board(board)
    pgn.headers.update(Event='StockBear Tournament1: Stage1 vs Hiddenclip',Site='Local CPU0 serial',
        Date=record['started_utc'][:10].replace('-','.'),Round=game['id'],White=game['white'],Black=game['black'],
        Result=record['result'],Termination=record['termination'],TimeControl='?',ThinkTimeMs='500',
        OpeningId=game['opening_id'],Opening=load('opening-suite.json')[game['opening']]['description'],
        OpeningFEN=load('opening-suite.json')[game['opening']]['fen'],PlanSHA256=record['config_sha256'],
        WhiteEngineSHA256=load('tournament-config.json')['engines'][game['white']]['sha256'],
        BlackEngineSHA256=load('tournament-config.json')['engines'][game['black']]['sha256'],
        HashMB='16',Threads='1',Ponder='false',Kernel='clip')
    return str(pgn)+'\n'


def validate_record(record, final=True):
    config=load('tournament-config.json')
    assert record['config_sha256']==core.sha(ROOT/'tournament-config.json')
    game=record['game']
    assert game in load('schedule.json')
    board=board_for(game,record['searches'])
    if final:
        result,reason=outcome(board,record['searches'],config)
        assert record['complete'] and record['result']==result and record['termination']==reason
        assert record['final_fen']==board.fen()
        parsed=chess.pgn.read_game(io.StringIO(pgn_text(record)))
        assert not parsed.errors and parsed.headers['Result']==result
        assert parsed.end().board().fen()==board.fen()
        assert [m.uci() for m in parsed.mainline_moves()]==[m.uci() for m in board.move_stack]
    return board


def completed():
    rows=[core.load(p) for p in sorted((ROOT/'games').glob('G[0-9][0-9][0-9].json'))]
    assert len({r['game']['id'] for r in rows})==len(rows)
    return rows


def progress(rows, current=None):
    result=dict(updated_utc=core.utc(),planned_games=80,completed_games=len(rows),remaining_games=80-len(rows),
                stats={label:core.stats(rows,label) for label in LABELS},current=current,
                failures=len(list((ROOT/'failures').glob('*.json'))))
    if rows:
        result['estimated_remaining_seconds']=(80-len(rows))*sum(r['elapsed_seconds'] for r in rows)/len(rows)
    save('progress.json',result)
    return result


def read_load(meter):
    current=meter.snapshot()
    idle,total,own=[x-y for x,y in zip(current,meter.previous)]
    if total<=0:
        return dict(other_cpu_percent=None,reason='interval below system accounting resolution')
    return dict(system_cpu_percent=100*(1-idle/total),benchmark_cpu_percent=100*own/total,
                other_cpu_percent=max(0,100*(1-idle/total)-100*own/total))


def play(game, config, rows):
    partial=ROOT/'games'/(game['id']+'.partial.json')
    if partial.exists():
        record=core.load(partial)
        board=validate_record(record,final=False)
        record['resumptions']+=1
        event('resume_partial',game=game['id'],saved_plies=len(record['searches']))
    else:
        record=dict(config_sha256=core.sha(ROOT/'tournament-config.json'),game=game,started_utc=core.utc(),
                    searches=[],resumptions=0,seconds=0,elapsed_seconds=0,complete=False)
        board=board_for(game)
    before=monitor.environment()
    assert before['ac_online'] and before['power_plan']==load('environment.json')['power_plan'],'Power interruption before game'
    record.setdefault('environment_sessions',[]).append(dict(before=before))
    started_game=time.monotonic()
    players={}
    try:
        with ExitStack() as stack:
            for label in (game['white'],game['black']):
                players[label]=stack.enter_context(player(label,game['id'],config))
            meter=monitor.Meter([os.getpid()]+[p.transport.get_pid() for p in players.values()])
            stack.callback(meter.close)
            handles={label:monitor.k.OpenProcess(0x1000,False,p.transport.get_pid()) for label,p in players.items()}
            for handle in handles.values():
                assert handle
                stack.callback(monitor.k.CloseHandle,handle)
            while True:
                result,reason=outcome(board,record['searches'],config)
                if result:
                    break
                if (ROOT/'STOP_REQUESTED').exists():
                    raise KeyboardInterrupt('Stop requested; checkpoint preserved')
                label=game['white' if board.turn else 'black']
                engine=players[label]
                meter.previous=meter.snapshot()
                cpu=monitor.cpu_seconds(handles[label])
                started=time.perf_counter()
                played=engine.play(board,chess.engine.Limit(time=.5),game=game['id'],info=chess.engine.INFO_ALL,ponder=False)
                wall=time.perf_counter()-started
                cpu=monitor.cpu_seconds(handles[label])-cpu
                background=read_load(meter)
                info=played.info
                if wall>.5+config['protocol_allowance_seconds'] or info.get('time',0)>.5+config['protocol_allowance_seconds']:
                    raise TimeoutError(f'500ms policy exceeded: wall={wall},reported={info.get("time")}')
                assert played.move and played.move in board.legal_moves,('Illegal move',played.move)
                replay=board.copy()
                for move in info.get('pv',[]):
                    assert move in replay.legal_moves,('Illegal PV',move)
                    replay.push(move)
                counters=dict(engine.protocol.counters)
                assert {'depth','nodes','nps','time','score'}.issubset(info)
                assert counters['eval_calls']==counters['nnue_evaluations']
                assert monitor.affinity(engine.transport.get_pid())==1
                row=dict(ply=len(record['searches'])+1,engine=label,side='white' if board.turn else 'black',
                    move=played.move.uci(),wall_seconds=wall,engine_seconds=info['time'],process_cpu_seconds=cpu,
                    nodes=info['nodes'],nps=info['nps'],wall_nps=info['nodes']/wall,depth=info['depth'],seldepth=info.get('seldepth'),
                    score_cp_white=info['score'].white().score(),mate_white=info['score'].white().mate(),
                    pv=[m.uci() for m in info.get('pv',[])],eval_calls=counters['eval_calls'],
                    nnue_evaluations=counters['nnue_evaluations'],qnodes=counters.get('qnodes'),counters=counters,
                    background=background,abnormal_delay=wall>config['abnormal_wall_seconds'] or info['time']>config['abnormal_engine_seconds'])
                record['searches'].append(row)
                record['seconds']+=wall
                board.push(played.move)
                core.save(partial,record)
                if len(record['searches'])%10==0:
                    progress(rows,dict(id=game['id'],plies=len(record['searches']),updated_utc=core.utc()))
            after=monitor.environment()
            record['environment_sessions'][-1]['after']=after
            assert after['ac_online'] and after['power_plan']==before['power_plan'],'Power interruption after game'
        record.update(complete=True,result=result,termination=reason,completed_utc=core.utc(),final_fen=board.fen(),
                      elapsed_seconds=record['elapsed_seconds']+time.monotonic()-started_game)
        validate_record(record)
        core.write_record(ROOT/'games'/(game['id']+'.pgn'),pgn_text(record))
        core.save(ROOT/'games'/(game['id']+'.json'),record)
        return record
    except BaseException as error:
        record['elapsed_seconds']+=time.monotonic()-started_game
        core.save(partial,record)
        event('interruption',game=game['id'],error=repr(error),saved_plies=len(record['searches']))
        if not isinstance(error,(KeyboardInterrupt,SystemExit)):
            save(f'failures/{game["id"]}-{time.time_ns()}.json',dict(error=repr(error),utc=core.utc(),game=game,
                searches=len(record['searches']),unscored=True,logs=[str(p.protocol.log_path) for p in players.values()]))
        raise


def code_hashes():
    paths=[Path(__file__),ROOT/'openings.py',REPO/'tools/nnue_showdown.py',REPO/'tools/match_optimizations.py',
           PRIOR/'validate.py',STAGE3/'load_meter.py',REPO/'StockBear_NNUE_training/stockbear/labeling/storage.py']
    return {p.relative_to(REPO).as_posix():core.sha(p) for p in paths}


def run(resume):
    config=config_check()
    preflight=load('preflight.json')
    assert preflight['passed'] and preflight['config_sha256']==core.sha(ROOT/'tournament-config.json')
    assert code_hashes()==load('runner-lock.json')
    rows=completed()
    for row in rows:
        validate_record(row)
    if len(rows)==80:
        print('All80 games already complete; no engines started',flush=True)
        from analyze import finalize
        finalize()
        return
    assert resume or (not rows and not list((ROOT/'games').glob('*.partial.json'))),'Use --resume'
    monitor.pin()
    with core.run_lock(ROOT),core.stay_awake():
        event('run_or_resume',pid=os.getpid(),completed_games=len(rows))
        progress(rows)
        for game in load('schedule.json'):
            if any(r['game']['id']==game['id'] for r in rows):
                continue
            config_check()
            print(f'Starting {game["id"]} {game["opening_id"]} {game["white"]} White',flush=True)
            result=play(game,config,rows)
            rows.append(result)
            progress(rows)
            print(f'Completed {len(rows)}/80: {game["id"]} {result["result"]} {result["termination"]}',flush=True)
        from analyze import finalize
        finalize()


def preflight():
    config=config_check()
    assert not completed(),'Never run preflight against live official tournament'
    monitor.pin()
    receipt=dict(config_sha256=core.sha(ROOT/'tournament-config.json'),checks=[],identities={},time_probes=[])
    suite=load('opening-suite.json')
    schedule=load('schedule.json')
    assert len(schedule)==80 and len(suite)==40
    for i,opening in enumerate(suite):
        board=board_for(schedule[2*i])
        assert board.is_valid() and len(board.move_stack)==len(opening['moves'])
        x,y=schedule[2*i:2*i+2]
        assert x['white']==y['black'] and x['black']==y['white']
    receipt['checks'].append('40 legal histories,80 exact assignments,40White/40Black each')
    with ExitStack() as stack:
        players={label:stack.enter_context(player(label,'preflight',config)) for label in LABELS}
        for label,engine in players.items():
            receipt['identities'][label]=core.identity(engine)
            record=capture(engine,dict(id='opening0',fen=suite[0]['fen'],moves=suite[0]['moves']),'time',500)
            assert record['wall_seconds']<.7
            assert any(line=='> go movetime 500' for line in engine.protocol.transcript)
            assert any(line.startswith('> position startpos moves '+' '.join(suite[0]['moves'])) for line in engine.protocol.transcript)
            receipt['time_probes'].append(dict(engine=label,**record))
        for opening in [suite[0],suite[10]]:
            row=dict(id=opening['id'],fen=opening['fen'],moves=opening['moves'])
            a,b=[capture(p,row,'nodes',200000) for p in players.values()]
            assert canonical(a)==canonical(b)
        receipt['checks'].append('Live identities,clip kernel,readiness,movetime500,legal PV,full UCI history,fixed-work parity')
    # Two bounded full smoke games from legal near-mate positions; separate from80 official games.
    receipt['smoke_games']=[]
    (ROOT/'smoke').mkdir(exist_ok=True)
    for white in LABELS:
        black=next(x for x in LABELS if x!=white)
        board=chess.Board('7k/5Q2/6K1/8/8/8/8/8 w - - 0 1')
        with player(white,'smoke-'+white,config) as engine:
            result=engine.play(board,chess.engine.Limit(time=.5),game=object(),info=chess.engine.INFO_ALL)
            assert result.move in board.legal_moves
            board.push(result.move)
        assert board.is_checkmate(),board.fen()
        pgn=chess.pgn.Game.from_board(board)
        pgn.headers.update(White=white,Black=black,Result='1-0',Event='Excluded smoke game')
        core.write_record(ROOT/'smoke'/(white+'.pgn'),str(pgn)+'\n')
        assert not chess.pgn.read_game(io.StringIO(str(pgn))).errors
        receipt['smoke_games'].append(dict(white=white,black=black,result='1-0',excluded=True))
    for fen,reason in [('7k/5Q2/6K1/8/8/8/8/8 b - - 0 1','stalemate'),
                       ('7k/8/8/8/8/8/8/K7 w - - 0 1','insufficient_material'),
                       ('8/6k1/8/8/8/8/R7/K7 w - - 100 1','fifty_moves')]:
        assert chess.Board(fen).outcome(claim_draw=True).termination.name.lower()==reason
    repeat=chess.Board()
    for move in ['g1f3','g8f6','f3g1','f6g8']*2:
        repeat.push_uci(move)
    assert repeat.outcome(claim_draw=True).termination==chess.Termination.THREEFOLD_REPETITION
    # Transactional checkpoint roundtrip and deterministic same-history restoration.
    mock=dict(config_sha256=core.sha(ROOT/'tournament-config.json'),game=schedule[0],searches=[])
    save('smoke/checkpoint-roundtrip.json',mock)
    assert core.load(ROOT/'smoke/checkpoint-roundtrip.json')==mock
    assert validate_record(mock,final=False).fen()==board_for(schedule[0]).fen()
    receipt['checks'].append('Mate/stalemate/material/50move/repetition rules,parseable smoke PGNs,atomic checkpoint and history resume roundtrip')
    assert core.sha(Path(config['engines'][LABELS[0]]['path']))==config['engines'][LABELS[0]]['sha256']
    receipt.update(passed=True,utc=core.utc())
    save('preflight.json',receipt)
    save('runner-lock.json',code_hashes())
    print('Preflight passed; two smoke games excluded; frozen80-game schedule ready',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['freeze','preflight','run','status','analyze'])
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    if args.action=='run':
        run(args.resume)
    elif args.action=='status':
        print(json.dumps(load('progress.json'),indent=2))
    elif args.action=='analyze':
        from analyze import finalize
        finalize()
    else:
        globals()[args.action]()
