"""Bounded native/GUI release checks; never runs games, training or benchmarks."""
import argparse
from dataclasses import replace
import hashlib
import json
import logging
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT']='1'
import chess
import chess.engine
logging.getLogger('chess.engine').setLevel(logging.ERROR)
import pygame
from app.engine_client import CLASSICAL_ENGINE, DEFAULT_ENGINE, EngineClient, EngineSettings
from app.application import Application
from tools.embed_nnue import DEFAULT_MODEL


class Protocol(chess.engine.UciProtocol):
    def __init__(self):
        super().__init__()
        self.evaluations=[]
        self.counters={}
    def line_received(self,line):
        import re
        if line.startswith('info string eval '):
            self.evaluations.append(json.loads(line[len('info string eval '):]))
            return
        self.counters.update({k:int(v) for k,v in re.findall(r'\b([a-z_]+) (\d+)\b',line)})
        super().line_received(line)


def probe(path,mode,fen):
    args=[str(path),'--eval']
    if mode=='nnue':args+=['--nnue','--kernel','clip']
    return json.loads(subprocess.check_output(args+[fen],text=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))


def search(path,mode,fen):
    with chess.engine.SimpleEngine.popen(Protocol,str(path),timeout=5,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0) as engine:
        engine.configure(dict(Evaluator=mode,Hash=16,**(dict(NNUEKernel='clip',NNUEIncremental=True) if mode=='nnue' else {})))
        engine.protocol.send_line('eval');engine.ping()
        identity=engine.protocol.evaluations[-1]
        assert identity.get('evaluator')=='nnue' and identity['kernel']=='clip' if mode=='nnue' else identity.get('advanced') is True and 'evaluator' not in identity
        board=chess.Board(fen)
        played=engine.play(board,chess.engine.Limit(nodes=20000),info=chess.engine.INFO_ALL)
        assert played.move in board.legal_moves
        counts=engine.protocol.counters
        assert counts['nnue_evaluations']==(counts['eval_calls'] if mode=='nnue' else 0)
        return dict(move=played.move.uci(),nodes=played.info['nodes'],depth=played.info['depth'],
            score=str(played.info['score'].white()),pv=[m.uci() for m in played.info.get('pv',[])])


def gui_check(output):
    # Observe real process creation/options while driving the actual application.
    original=chess.engine.SimpleEngine.popen_uci
    opened=[];configured=[]
    def tracked(command,*args,**kwargs):
        assert all(p.transport.get_returncode() is not None for p in opened),'Overlapping engine processes'
        engine=original(command,*args,**kwargs)
        opened.append(engine)
        configure=engine.configure
        def observe(options):
            configured.append(dict(path=str(command),options=dict(options)))
            return configure(options)
        engine.configure=observe
        return engine
    chess.engine.SimpleEngine.popen_uci=tracked
    app=Application(settings=EngineSettings(enabled=True,thinking_time_ms=500))
    try:
        assert app.game.play(chess.Move.from_uci('e2e4'))
        start_fen=app.game.board.fen()
        # Change mode during a live search, preserving board/revision and rejecting stale work.
        app.update_engine()
        for mode in ['nnue','classical','nnue']:
            app.draft_settings=replace(app.settings,evaluator=mode)
            app.settings_dialog=True
            app.panel_action('apply')
            assert app.game.board.fen()==start_fen
            app.update_engine()
            time.sleep(.04)
        deadline=time.monotonic()+6
        while len(app.game.records)<2:
            app.update_engine()
            assert not app.engine_error,app.engine_error
            assert time.monotonic()<deadline
            time.sleep(.005)
        assert app.last_play_stats.evaluator=='nnue'
        assert len(app.game.board.move_stack)==2
        assert any(c['options'].get('NNUEKernel')=='clip' for c in configured)
        app.diagnostics_dialog=True;app.draw()
        pygame.image.save(app.surface,output/'gui-nnue.png')
        # Reverse selection, reset board, and obtain a fresh classical move.
        app.diagnostics_dialog=False
        app.draft_settings=replace(app.settings,evaluator='classical')
        app.settings_dialog=True;app.panel_action('apply')
        app.action('new')
        assert app.game.board.fen()==chess.STARTING_FEN
        assert app.game.play(chess.Move.from_uci('d2d4'))
        app.update_engine();deadline=time.monotonic()+6
        while len(app.game.records)<2:
            app.update_engine();assert not app.engine_error,app.engine_error
            assert time.monotonic()<deadline;time.sleep(.005)
        assert app.last_play_stats.evaluator=='classical'
        app.diagnostics_dialog=True;app.draw();pygame.image.save(app.surface,output/'gui-classical.png')
    finally:
        app.close()
        chess.engine.SimpleEngine.popen_uci=original
    assert opened and all(p.transport.get_returncode() is not None for p in opened)
    assert any(c['path']==str(CLASSICAL_ENGINE) for c in configured)
    assert any(c['path']==str(DEFAULT_ENGINE) and c['options'].get('Evaluator')=='nnue' for c in configured)
    return dict(passed=True,real_engine_processes=len(opened),max_concurrent_processes=1,
        switching='classical->nnue->classical->nnue;reset->classical',board_preserved=True,stale_replies_rejected=True,
        orphaned_processes=0,method='Actual Pygame application with SDL dummy; desktop inspection recorded separately')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuilt',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'release')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    provenance=json.loads((ROOT/'release/provenance.json').read_text())
    for rel,entry in provenance['frozen_assets'].items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==entry['sha256'],rel
    goldens=json.loads(DEFAULT_MODEL.with_suffix('.golden.json').read_text())
    paths=[DEFAULT_ENGINE]+([args.rebuilt.resolve()] if args.rebuilt else [])
    fens=[chess.STARTING_FEN,goldens[0]['fen'],'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1']
    for path in paths:
        for row in goldens:
            value=probe(path,'nnue',row['fen'])
            assert value['kernel']=='clip' and value['sha256']=='a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3'
            assert abs(value['side_to_move_cp']-row['side_to_move_cp'])<.01
            reference=probe(DEFAULT_ENGINE,'nnue',row['fen'])
            assert {k:v for k,v in value.items() if k!='model'}=={k:v for k,v in reference.items() if k!='model'},'Rebuilt NNUE parity'
        for fen in fens:
            assert probe(path,'classical',fen)==probe(CLASSICAL_ENGINE,'classical',fen)
            for mode in ['classical','nnue']:
                assert search(path,mode,fen)==search(CLASSICAL_ENGINE if mode=='classical' else DEFAULT_ENGINE,mode,fen)
    result=dict(passed=True,golden_positions=len(goldens),checked_binaries=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths],
        classical_full_components_exact=True,nnue_native_exact=True,fixed_work_decisions_exact=True,
        gui=gui_check(args.output),no_training=True,no_tournament=True)
    (args.output/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
