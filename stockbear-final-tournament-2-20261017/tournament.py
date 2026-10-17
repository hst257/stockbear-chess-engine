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
sys.path.insert(0,str(ROOT))
T1=REPO/'stockbear-final-tournament-1-20261017'

LABELS=('CLASSICAL','NNUE_HIDDENCLIP')


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
    finalist=core.load(T1/'TOURNAMENT_1_FINALIST.json')
    previous=core.load(REPO/'final-nnue-showdown-20261017/plan.json')
    classical=previous['engines']['classical']
    assert finalist['selected_engine']=='NNUE_HIDDENCLIP'
    assert finalist['executable_sha256']=='68ced7162b20109b6ad9e705bbb4f43317c85d2cb5d10ff3ae45a02eb0bd571b'
    assert classical['evaluator']=='classical'
    assert classical['sha256']=='ffd785d4e8eecacbf6822d98f4a7b6f43972ea89e20c45d0135227e745eab606'
    assert core.sha(Path(classical['path']))==core.sha(Path(classical['source_path']))==classical['sha256']
    assert core.sha(Path(finalist['executable']))==finalist['executable_sha256']
    identities=monitor.identities()
    save('binary-identities.json',identities)
    copied=STAGE3/'artifacts/hiddenclip-source'
    differences=[];matches={}
    for rel,digest in classical['build']['source_sha256'].items():
        name=rel.replace(chr(92),'/').split('/')[-1]
        actual=core.sha(copied/name)
        if actual!=digest:
            differences.append(name)
        else:
            matches[name]=actual
    assert set(differences)=={'main.cpp','nnue.cpp'},differences
    # Original source is still present and matches the classical build receipt.
    for rel,digest in classical['build']['source_sha256'].items():
        assert core.sha(REPO/rel.replace(chr(92),'/'))==digest,rel
    original_main=(REPO/'engine/src/main.cpp').read_text()
    new_main=(copied/'main.cpp').read_text()
    assert original_main.replace('var scalar var quant','var scalar var quant var clip')==new_main
    save('provenance.json',dict(classical=classical,nnue=finalist,
        identical_source_files=matches,differing_source_files=differences,
        explanation='Only main.cpp adds clip UCI choice and nnue.cpp uses preserved float head; new stage1_head.hpp implements that head. Search.cpp and all existing headers, rules, evaluation.cpp, flags and vendor unchanged. No unrelated search changes.',
        head_build=core.load(STAGE3/'build-hiddenclip-engine.json'),
        stage1_build=core.load(REPO/'nnue-optimization-stage1-20261017/build-variant-engine.json')))
    protected=core.load(T1/'preservation-before.json')
    for rel in core.load(T1/'manifest.json')['files']:
        protected[(T1/rel).relative_to(REPO).as_posix()]=core.sha(T1/rel)
    protected[(T1/'manifest.json').relative_to(REPO).as_posix()]=core.sha(T1/'manifest.json')
    for path in (REPO/'engine/src').glob('*'):
        if path.is_file(): protected[path.relative_to(REPO).as_posix()]=core.sha(path)
    save('preservation-before.json',{rel:core.sha(REPO/rel) for rel in protected})
    shutil.copy2(T1/'opening-suite.json',ROOT/'opening-suite.json')
    suite=load('opening-suite.json')
    assert len(suite)==40
    schedule=core.load(T1/'schedule.json')
    for game in schedule:
        for k in ['white','black']:
            game[k]=game[k].replace('NNUE_STAGE1','CLASSICAL')
        game['pair']=list(LABELS)
    save('schedule.json',schedule)
    config=core.load(T1/'tournament-config.json')
    config.update(created_utc=core.utc(),games=80,opening_pairs=40,
        openings_sha256=core.sha(ROOT/'opening-suite.json'),schedule_sha256=core.sha(ROOT/'schedule.json'))
    options=finalist['required_uci_options']
    class_options=dict(options,Evaluator='classical',NNUEKernel='scalar')
    engines={
        'CLASSICAL':dict(name='CLASSICAL',path=classical['path'],sha256=classical['sha256'],evaluator='classical',options=class_options),
        'NNUE_HIDDENCLIP':dict(name='NNUE_HIDDENCLIP',path=finalist['executable'],sha256=finalist['executable_sha256'],
            evaluator='nnue',kernel='clip',network_sha256=finalist['nnue_model']['export_sha256'],width=64,hidden=32,options=options)}
    config['engines']=engines
    config['rules']['winner']='A: NNUE pair95 lower>50% and valid -> NNUE; B: NNUE upper<50% and valid -> CLASSICAL; C: inconclusive -> CLASSICAL conservative baseline, not proof of higher Elo; D: critical failure -> NO VALID CHAMPION. No promotion.'
    config['rules']['limits']='Exactly80 Tournament2 official games; excluded bounded smoke; no extension, cleanup, training, labeling, deployment or engine changes'
    config['rules']['statistics']='Same Tournament1 50000-draw opening-pair bootstrap seed2026101780; family-cluster sensitivity secondary; no pooling with historical games'
    save('tournament-config.json',config)
    save('environment.json',monitor.environment())
    print('Frozen exact Tournament1 opening bytes and80 Tournament2 games',flush=True)


def config_check():
    config=load('tournament-config.json')
    assert core.sha(ROOT/'opening-suite.json')==config['openings_sha256']==core.sha(T1/'opening-suite.json')
    assert core.sha(ROOT/'schedule.json')==config['schedule_sha256']
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
        engine.configure(entry['options'])
        engine.ping()
        actual=core.identity(engine)
        if entry['evaluator']=='nnue':
            assert actual['evaluator']=='nnue',actual
            assert all(actual[k]==value for k,value in [('kernel','clip'),('sha256',entry['network_sha256']),('width',64),('hidden',32)]),actual
        else:
            assert 'components' in actual and actual.get('advanced') is True and 'evaluator' not in actual and 'sha256' not in actual,actual
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
    pgn.headers.update(Event='StockBear Tournament2: Classical vs Hiddenclip',Site='Local CPU0 serial',
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
                assert counters['nnue_evaluations']==(counters['eval_calls'] if config['engines'][label]['evaluator']=='nnue' else 0)
                assert monitor.affinity(engine.transport.get_pid())==1
                row=dict(ply=len(record['searches'])+1,engine=label,side='white' if board.turn else 'black',
                    move=played.move.uci(),wall_seconds=wall,engine_seconds=info['time'],process_cpu_seconds=cpu,
                    protocol_delay_proxy_seconds=max(0,wall-info['time']),requested_time_ms=500,
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
    paths=[Path(__file__),ROOT/'analyze.py',ROOT/'launch.py',REPO/'tools/nnue_showdown.py',REPO/'tools/match_optimizations.py',
           PRIOR/'validate.py',STAGE3/'load_meter.py',REPO/'StockBear_NNUE_training/stockbear/labeling/storage.py']
    return {p.relative_to(REPO).as_posix():core.sha(p) for p in paths}


def run(resume):
    config=config_check()
    preflight=load('preflight.json')
    assert preflight['passed'] and preflight['config_sha256']==core.sha(ROOT/'tournament-config.json')
    rows=completed()
    for row in rows:
        validate_record(row)
    if len(rows)==80:
        print('All80 games already complete; no engines started',flush=True)
        subprocess.run([sys.executable,'-u',str(ROOT/'analyze.py')],cwd=REPO,check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
        return
    assert code_hashes()==load('runner-lock.json')
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
        subprocess.run([sys.executable,'-u',str(ROOT/'analyze.py')],cwd=REPO,check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)


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
            assert engine.protocol.counters['nnue_evaluations']==(engine.protocol.counters['eval_calls'] if label=='NNUE_HIDDENCLIP' else 0)
            assert any(line=='> go movetime 500' for line in engine.protocol.transcript)
            assert any(line.startswith('> position startpos moves '+' '.join(suite[0]['moves'])) for line in engine.protocol.transcript)
            receipt['time_probes'].append(dict(engine=label,**record))
        receipt['checks'].append('Live correct evaluator identities,readiness,movetime500,legal PV,full UCI history; NNUE clip active, classical zero NNUE calls')
        for label,engine in players.items():
            raw=(ROOT/'logs/preflight'/(label+'.log')).read_text()
            assert ' > ucinewgame' in raw
    receipt['search_source_parity']=load('provenance.json')['identical_source_files']
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
        subprocess.run([sys.executable,'-u',str(ROOT/'analyze.py')],cwd=REPO,check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        globals()[args.action]()
