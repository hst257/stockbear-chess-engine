"""Bounded native/GUI release checks; never runs games, training or benchmarks."""
import argparse
import asyncio
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
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
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
        self.evaluations = []
        self.counters = {}

    def line_received(self, line):
        import re
        if line.startswith('info string eval '):
            self.evaluations.append(json.loads(line[len('info string eval '):]))
            return
        self.counters.update({k: int(v) for k, v in re.findall('\\b([a-z_]+) (\\d+)\\b', line)})
        super().line_received(line)

def probe(path: Path, mode: str, fen: str) -> dict:
    args = [str(path), '--eval']
    if mode == 'nnue':
        args += ['--nnue', '--kernel', 'clip']
    return json.loads(subprocess.check_output(args + [fen], text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))

def identity(engine: chess.engine.SimpleEngine) -> dict:

    class Probe(chess.engine.BaseCommand):

        def start(self):
            self.value = None
            self._engine.send_line('eval')
            self._engine.send_line('isready')

        def line_received(self, line):
            if line.startswith('info string eval '):
                self.value = json.loads(line[len('info string eval '):])
            elif line == 'readyok':
                self.result.set_result(self.value)
                self.set_finished()

    async def request():
        return await engine.protocol.communicate(Probe)
    return asyncio.run_coroutine_threadsafe(request(), engine.protocol.loop).result(timeout=5)

def search(path: Path, mode: str, fen: str) -> dict:
    engine = chess.engine.SimpleEngine.popen(Protocol, str(path), timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        engine.configure(dict(Evaluator=mode, Hash=16, **dict(NNUEKernel='clip', NNUEIncremental=True) if mode == 'nnue' else {}))
        actual = identity(engine)
        assert actual.get('evaluator') == 'nnue' and actual['kernel'] == 'clip' if mode == 'nnue' else actual.get('advanced') is True and 'evaluator' not in actual
        board = chess.Board(fen)
        played = engine.play(board, chess.engine.Limit(nodes=20000), info=chess.engine.INFO_ALL)
        assert played.move in board.legal_moves
        counts = engine.protocol.counters
        assert counts['nnue_evaluations'] == (counts['eval_calls'] if mode == 'nnue' else 0)
        return dict(move=played.move.uci(), nodes=played.info['nodes'], depth=played.info['depth'], score=str(played.info['score'].white()), pv=[m.uci() for m in played.info.get('pv', [])])
    finally:
        try:
            engine.quit()
        finally:
            engine.close()

def gui_check(output: Path) -> dict:
    original = chess.engine.SimpleEngine.popen_uci
    opened = []
    configured = []

    def tracked(command, *args, **kwargs):
        assert all((p.transport.get_returncode() is not None for p in opened)), 'Overlapping engine processes'
        engine = original(command, *args, **kwargs)
        opened.append(engine)
        configure = engine.configure

        def observe(options):
            configured.append(dict(path=str(command), options=dict(options)))
            return configure(options)
        engine.configure = observe
        return engine
    chess.engine.SimpleEngine.popen_uci = tracked
    app = Application(settings=EngineSettings(enabled=True, thinking_time_ms=500))
    try:
        assert app.game.play(chess.Move.from_uci('e2e4'))
        start_fen = app.game.board.fen()
        app.update_engine()
        for mode in ['nnue', 'classical', 'nnue']:
            app.draft_settings = replace(app.settings, evaluator=mode)
            app.settings_dialog = True
            app.panel_action('apply')
            assert app.game.board.fen() == start_fen
            app.update_engine()
            time.sleep(0.04)
        deadline = time.monotonic() + 6
        while len(app.game.records) < 2:
            app.update_engine()
            assert not app.engine_error, app.engine_error
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert app.last_play_stats.evaluator == 'nnue'
        assert len(app.game.board.move_stack) == 2
        assert any((c['options'].get('NNUEKernel') == 'clip' for c in configured))
        app.diagnostics_dialog = True
        app.draw()
        pygame.image.save(app.surface, output / 'gui-nnue.png')
        app.diagnostics_dialog = False
        app.draft_settings = replace(app.settings, evaluator='classical')
        app.settings_dialog = True
        app.panel_action('apply')
        app.action('new')
        assert app.game.board.fen() == chess.STARTING_FEN
        assert app.game.play(chess.Move.from_uci('d2d4'))
        app.update_engine()
        deadline = time.monotonic() + 6
        while len(app.game.records) < 2:
            app.update_engine()
            assert not app.engine_error, app.engine_error
            assert time.monotonic() < deadline
            time.sleep(0.005)
        assert app.last_play_stats.evaluator == 'classical'
        app.diagnostics_dialog = True
        app.draw()
        pygame.image.save(app.surface, output / 'gui-classical.png')
    finally:
        app.close()
        chess.engine.SimpleEngine.popen_uci = original
    assert opened and all((p.transport.get_returncode() is not None for p in opened))
    assert any((c['path'] == str(CLASSICAL_ENGINE) for c in configured))
    assert any((c['path'] == str(DEFAULT_ENGINE) and c['options'].get('Evaluator') == 'nnue' for c in configured))
    return dict(passed=True, real_engine_processes=len(opened), max_concurrent_processes=1, switching='classical->nnue->classical->nnue;reset->classical', board_preserved=True, stale_replies_rejected=True, orphaned_processes=0, method='Actual Pygame application with SDL dummy; desktop inspection recorded separately')

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuilt', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((ROOT / 'release/provenance.json').read_text())
    for rel, entry in provenance['frozen_assets'].items():
        data = (ROOT / rel).read_bytes()
        exact = hashlib.sha256(data).hexdigest() == entry['sha256']
        text_equivalent = rel.endswith('.json') and hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest() == entry.get('lf_sha256')
        assert exact or text_equivalent, rel
    goldens = json.loads(DEFAULT_MODEL.with_suffix('.golden.json').read_text())
    paths = [DEFAULT_ENGINE] + ([args.rebuilt.resolve()] if args.rebuilt else [])
    fens = [chess.STARTING_FEN, goldens[0]['fen'], 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1']
    for path in paths:
        for row in goldens:
            value = probe(path, 'nnue', row['fen'])
            assert value['kernel'] == 'clip' and value['sha256'] == 'a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3'
            assert abs(value['side_to_move_cp'] - row['side_to_move_cp']) < 0.01
            reference = probe(DEFAULT_ENGINE, 'nnue', row['fen'])
            assert {k: v for k, v in value.items() if k != 'model'} == {k: v for k, v in reference.items() if k != 'model'}, 'Rebuilt NNUE parity'
        for fen in fens:
            assert probe(path, 'classical', fen) == probe(CLASSICAL_ENGINE, 'classical', fen)
            for mode in ['classical', 'nnue']:
                assert search(path, mode, fen) == search(CLASSICAL_ENGINE if mode == 'classical' else DEFAULT_ENGINE, mode, fen)
    result = dict(passed=True, golden_positions=len(goldens), checked_binaries=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths], classical_full_components_exact=True, nnue_native_exact=True, fixed_work_decisions_exact=True, gui=gui_check(args.output), no_training=True, no_tournament=True)
    import threading
    deadline = time.monotonic() + 3
    while any((t is not threading.main_thread() and (not t.daemon) for t in threading.enumerate())) and time.monotonic() < deadline:
        time.sleep(0.01)
    remaining = [t.name for t in threading.enumerate() if t is not threading.main_thread() and (not t.daemon)]
    if remaining:
        import faulthandler
        faulthandler.dump_traceback()
        raise RuntimeError('Verification background threads did not shut down: ' + str(remaining))
    result['background_threads_after_shutdown'] = remaining
    (args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)
if __name__ == '__main__':
    main()
