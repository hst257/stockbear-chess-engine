"""Independently audit saved exports after the standalone process has exited."""
import collections
import csv
import io
import json
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
    recovery=t.load('harness-recovery.json')
    key='stockbear-final-tournament-1-20261017/tournament.py'
    assert t.core.sha(t.ROOT/'provenance/executed-tournament.py')==locked[key]==recovery['original_runner_sha256']
    assert actual[key]==recovery['repaired_runner_sha256']
    actual[key]=locked[key]
    assert actual==locked
    with (t.ROOT/'games.csv').open(newline='',encoding='utf-8') as f:
        games=list(csv.DictReader(f))
    with (t.ROOT/'moves.csv').open(newline='',encoding='utf-8') as f:
        moves=list(csv.DictReader(f))
    assert len(games)==80 and len({g['game_id'] for g in games})==80
    assert len(moves)==sum(len(r['searches']) for r in rows)
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
    handoff=t.load('TOURNAMENT_1_FINALIST.json')
    assert handoff['selected_engine']==analysis['selected']
    if handoff['selected_engine']:
        assert t.core.sha(Path(handoff['executable']))==handoff['executable_sha256']
        assert handoff['required_uci_options']==config['options']
    for rel,digest in t.load('preservation-before.json').items():
        assert t.core.sha(t.REPO/rel)==digest,rel
    t.save('final-audit.json',dict(passed=True,utc=t.core.utc(),official_games=80,
        opening_pairs=40,moves_csv_rows=len(moves),all_parseable_pgn_files=pgns,
        all_parsed_pgn_games_including_smoke_and_aggregate=parsed_games,
        matching_go_movetime500_commands=len(moves),color_balance=True,all_protected_files_unchanged=True))
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
