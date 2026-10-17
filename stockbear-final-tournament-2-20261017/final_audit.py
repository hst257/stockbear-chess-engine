"""Independently audit saved exports after the standalone process has exited."""
import collections
import csv
import io
import json
import math
from pathlib import Path
import tournament as t


def main():
    config=t.config_check()
    rows=t.completed()
    schedule=t.load('schedule.json')
    assert len(rows)==80
    assert {r['game']['id'] for r in rows}=={g['id'] for g in schedule}
    assert all(r['game']==schedule[int(r['game']['id'][1:])-1] for r in rows)
    actual=t.code_hashes()
    locked=t.load('runner-lock.json')
    assert actual==locked
    with (t.ROOT/'games.csv').open(newline='',encoding='utf-8') as f:
        games=list(csv.DictReader(f))
    with (t.ROOT/'moves.csv').open(newline='',encoding='utf-8') as f:
        moves=list(csv.DictReader(f))
    assert len(games)==80 and len({g['game_id'] for g in games})==80
    assert len(moves)==sum(len(r['searches']) for r in rows)
    authoritative=[dict(game_id=r['game']['id'],opening_id=r['game']['opening_id'],**m) for r in rows for m in r['searches']]
    for raw,expected in zip(moves,authoritative):
        for key,value in expected.items():
            rendered=json.dumps(value) if isinstance(value,(list,dict)) else '' if value is None else str(value)
            assert raw[key]==rendered,(raw['game_id'],raw['ply'],key)

    grouped=collections.Counter(m['game_id'] for m in moves)
    pgns=0;parsed_games=0
    for path in t.ROOT.rglob('*.pgn'):
        with path.open(encoding='utf-8') as f:
            count=0
            while (game:=t.chess.pgn.read_game(f)) is not None:
                assert not game.errors,path
                count+=1
            assert count>0,path
        pgns+=1;parsed_games+=count
    official=[]
    with (t.ROOT/'games.pgn').open(encoding='utf-8') as f:
        while (game:=t.chess.pgn.read_game(f)) is not None:
            official.append(game)
    assert len(official)==80 and len({g.headers['Round'] for g in official})==80
    exports={g['game_id']:g for g in games}
    for r,pgn in zip(rows,official):
        gid=r['game']['id'];t.validate_record(r)
        assert grouped[gid]==len(r['searches'])
        assert exports[gid]['result']==r['result']==pgn.headers['Result']
        assert pgn.headers['Round']==gid and pgn.headers['White']==r['game']['white'] and pgn.headers['Black']==r['game']['black']
        assert pgn.end().board().fen()==r['final_fen']
        board=t.board_for(r['game'])
        for move in r['searches']:
            assert move['requested_time_ms']==500 and move['wall_seconds']<=.7 and move['engine_seconds']<=.7
            assert move['protocol_delay_proxy_seconds']==max(0,move['wall_seconds']-move['engine_seconds'])
            assert move['nnue_evaluations']==(move['eval_calls'] if move['engine']=='NNUE_HIDDENCLIP' else 0)
            assert move['nodes']>=0 and move['depth']>=0
            probe=board.copy()
            for uci in move['pv']:
                parsed=t.chess.Move.from_uci(uci)
                assert parsed in probe.legal_moves
                probe.push(parsed)
            board.push_uci(move['move'])
        assert [m.uci() for m in pgn.mainline_moves()]==[m.uci() for m in board.move_stack]

        for label in t.LABELS:
            raw=(t.ROOT/'logs'/gid/(label+'.log')).read_text(encoding='utf-8')
            commands=[line.split(' > ',1)[1] for line in raw.splitlines() if ' > go ' in line]
            assert len(commands)==sum(m['engine']==label for m in r['searches'])
            assert all(line=='go movetime 500' for line in commands)
    analysis=t.load('analysis.json')
    assert sum(analysis['stats'][label]['points'] for label in t.LABELS)==80
    for label in t.LABELS:
        assert analysis['stats'][label]['games']==80
        assert sum(r['game']['white']==label for r in rows)==sum(r['game']['black']==label for r in rows)==40
    handoff=t.load('STOCKBEAR_FINAL_CHAMPION.json')
    assert handoff['selected_engine']==analysis['selected']
    if handoff['selected_engine']:
        assert t.core.sha(Path(handoff['executable']))==handoff['executable_sha256']
        assert handoff['required_uci_options']==config['engines'][handoff['selected_engine']]['options']
    if handoff['selected_engine']:
        selected=handoff['selected_engine']
        bounds=analysis['hiddenclip_pair_score95']
        selected_bounds=bounds if selected=='NNUE_HIDDENCLIP' else [1-bounds[1],1-bounds[0]]
        selected_fraction=analysis['stats'][selected]['score_fraction']
        def elo(p):
            return '-infinity' if p<=0 else '+infinity' if p>=1 else -400*math.log10(1/p-1)
        handoff['selected_result']=dict(wins=analysis['stats'][selected]['wins'],draws=analysis['stats'][selected]['draws'],
            losses=analysis['stats'][selected]['losses'],score_percentage=100*selected_fraction,
            score_fraction95=selected_bounds,elo_equivalent=elo(selected_fraction),elo_equivalent95=[elo(p) for p in selected_bounds],
            orientation='Selected engine relative to the other finalist')
        t.save('STOCKBEAR_FINAL_CHAMPION.json',handoff)
    for rel,digest in t.load('preservation-before.json').items():
        assert t.core.sha(t.REPO/rel)==digest,rel
    report_path=t.ROOT/'STOCKBEAR_GRAND_FINAL_REPORT.md'
    report=report_path.read_text(encoding='utf-8')
    typography={
        'Exactly80':'Exactly 80','at500ms':'at 500 ms','pairs. NNUE':'pairs. NNUE',
        'paired95%':'paired 95%','original64/32':'original 64/32','Tournament1':'Tournament 1',
        'Tournament2':'Tournament 2','Stage1':'Stage 1','RuleB':'Rule B',
        'clip kernel, incremental float32,780':'clip kernel, incremental float32, 780',
        'All40':'All 40','The80':'The 80','plays40White/40Black':'plays 40 games as White and 40 as Black',
        'Seed2026101780':'Seed 2026101780','seed2026101780':'seed 2026101780',
        'go movetime500':'`go movetime 500`','16MiB':'16 MiB','one search thread,no':'one search thread, no',
        'clocks,UCI':'clocks, UCI','rules,PGNs':'rules, PGNs','evaluator counters, clocks':'evaluator counters, clocks',
        ';400 searched':'; 400 searched','Full80':'Full 80','method:50,000':'method: 50,000',
        'of40 complete':'of 40 complete','excludes50%':'excludes 50%',
        'requests500ms':'requests 500 ms','symmetric200ms':'symmetric 200 ms',
        ';700ms':'; 700 ms','>550ms':'>550 ms','>525ms':'>525 ms',
        ',frozen1%':', frozen 1%','game failures':'game failures',
        'Quiet/Eco':'Quiet/Eco','historically15.625ms':'historically 15.625 ms',
        'hiddenclip32wins,Stage 1 28wins,20draws':'Hiddenclip 32 wins, Stage 1 28 wins, 20 draws',
        'older48-game1second':'older 48-game, 1-second','classical13/24':'classical 13/24','and17.5/24':'and 17.5/24',
        'Stage3.1':'Stage 3.1','cases,no':'cases, no','Symmetric500ms':'Symmetric 500 ms',
        'and700ms':'and 700 ms','Limits:80 games,40 fixed pairs,one laptop,one time budget':'Limits: 80 games, 40 fixed pairs, one laptop, one time budget',
        'unique scheduled games,40 reversed pairs,40White/40Black each':'unique scheduled games, 40 reversed pairs, 40 White/40 Black each',
        'No training,labeling,source/model/default change,cleanup':'No training, labeling, source/model/default change, cleanup',
        'NNUE feature':'NNUE feature'
    }
    for old,new in typography.items():
        report=report.replace(old,new)
    roots=analysis['matched_opening_roots']
    report+=f"\n## Matched opening-root search diagnostic\n\nAcross the same 40 opening histories, NNUE/classical wall-NPS geometric mean was {roots['nnue_relative_wall_nps_geomean']:.4f}; NNUE-minus-classical mean completed depth was {roots['nnue_minus_classical_mean_depth']:+.3f} plies. Both searched for the same nominal 500 ms with fresh state. Different evaluators explore different trees, so this exploratory root comparison is not an isolated inference-cost measurement.\n"
    # Idempotent repeated audits must not duplicate the derived diagnostic section.
    marker='\n## Matched opening-root search diagnostic\n'
    first=report.find(marker)
    if first!=report.rfind(marker):
        report=report[:report.rfind(marker)]
    t.core.write_record(report_path,report)
    t.save('final-audit.json',dict(passed=True,utc=t.core.utc(),official_games=80,
        opening_pairs=40,moves_csv_rows=len(moves),all_parseable_pgn_files=pgns,
        all_parsed_pgn_games_including_smoke_and_aggregate=parsed_games,
        matching_go_movetime500_commands=len(moves),csv_values_match_authoritative_json=True,all_pvs_legal=True,correct_evaluator_every_search=True,color_balance=True,all_protected_files_unchanged=True))
    # Include settled launcher logs as well as every data/receipt/script file.
    manifest=t.load('manifest.json')
    for path in sorted(t.ROOT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or 'artifacts' in path.parts or path.name=='manifest.json':
            continue
        data=path.read_bytes()
        manifest['files'][path.relative_to(t.ROOT).as_posix()]=dict(bytes=len(data),sha256=t.core.sha(path),
            lf_sha256=t.core.hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest())
    manifest['final_audit_utc']=t.core.utc()
    t.save('manifest.json',manifest)
    print(json.dumps(t.load('final-audit.json')),flush=True)


if __name__=='__main__':
    main()
