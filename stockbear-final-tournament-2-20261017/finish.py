"""Complete the resumed tournament audit and refresh its reproducible delivery manifest."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tournament as t


def main():
    rows=t.completed()
    assert len(rows)==80,'Finish only after all80 frozen games'
    snapshot=t.load('pause-manifest.json')
    checked=[]
    for name,entry in snapshot['files'].items():
        match=re.match(r'(?:games|logs)/(G[0-9]{3})(?:[./])',name)
        if match and int(match[1][1:])<=67:
            assert t.core.sha(t.ROOT/name)==entry['sha256'],name
            checked.append(name)
    assert len([p for p in checked if re.fullmatch(r'games/G[0-9]{3}\.json',p)])==67
    assert sum(r['resumptions'] for r in rows)==1
    resumed=next(r for r in rows if r['resumptions'])
    assert resumed['game']['id']=='G068'
    boundary=t.load('pause-audit.json')
    assert boundary['next_game_saved_searches']==0 and boundary['completed_games']==67
    t.save('resume-audit.json',dict(passed=True,utc=t.core.utc(),completed_before_pause=67,
        completed_after_resume=13,completed_game_artifacts_byte_unchanged=len(checked),
        resumed_game='G068',saved_searches_before_resume=0,replayed_completed_games=0,
        frozen_runner_lock_unchanged=t.code_hashes()==t.load('runner-lock.json'),
        reason='User manually resumed after scheduled continuation did not activate; no extra games'))
    report=t.ROOT/'STOCKBEAR_GRAND_FINAL_REPORT.md'
    text=report.read_text(encoding='utf-8')
    marker='\n## Planned pause and manual continuation\n'
    if marker not in text:
        text+=marker+'\nThe user requested a pause when65 games were complete, allowing exactly two more. Games66 and67 finished before the runner stopped; game68 had zero searched moves. The remaining13 games resumed manually on October18 after the scheduling request returned a setup card without confirmed activation. All67 completed game records,PGNs,partial snapshots and protocol logs match the pre-pause checksums byte-for-byte. No completed game was replayed. G068 records one reconstruction with fresh engines, but no within-game searches or warm caches were discarded at the boundary. The KeyboardInterrupt in the first runner error log is the expected requested pause,not an engine failure. Separate sessions introduce possible environmental drift despite unchanged AC/power-plan/affinity policy. No thermal cause is inferred. pause-manifest.json is the historical67-game snapshot; manifest.json is the completed delivery manifest.\n'
        t.core.write_record(report,text)
    state='# Tournament 2 complete\n\nAll **80/80** official games are complete; none remain. Read STOCKBEAR_GRAND_FINAL_REPORT.md, STOCKBEAR_FINAL_CHAMPION.json and completion.json. No additional games are authorized.\n\nThe user-requested67-game pause and manual continuation are documented in pause-audit.json and resume-audit.json; PAUSED.md and pause-manifest.json are historical snapshots. No engine/default/model was changed or promoted.\n\nTo audit the saved outputs without starting engines:\n\n```powershell\n.\\.venv\\Scripts\\python.exe .\\stockbear-final-tournament-2-20261017\\final_audit.py\n```\n'
    t.core.write_record(t.ROOT/'RESUME.md',state)
    readme=(t.ROOT/'README.md').read_text(encoding='utf-8')
    if readme.startswith('# Current state: paused'):
        readme=readme[readme.index('# Tournament 2:'):]
    t.core.write_record(t.ROOT/'README.md',state+'\n## Historical standalone execution commands\n\nThe commands below describe the frozen runner. A completed resume skips all80 games and starts no searches.\n\n'+readme)
    subprocess.run([sys.executable,str(t.ROOT/'final_audit.py')],cwd=t.REPO,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    audit=t.load('final-audit.json');assert audit['passed']
    # Report typography only; frozen estimators, selection and raw data unchanged.
    report_text=report.read_text(encoding='utf-8')
    report_text=re.sub(r',(?=[A-Za-z])',', ',report_text)
    for old,new in {'False** (interval excludes 50%)':'False** (the interval contains 50%)',
        'when65':'when 65','Games66 and67':'Games 66 and 67','game68':'game 68',
        'remaining13':'remaining 13','October18':'October 18','All67':'All 67',
        'historical67':'historical 67','user-requested67':'user-requested 67',
        'NNUE95%':'NNUE 95%','RuleC':'Rule C','ms,40':'ms, 40','hash,one':'hash, one',
        'against64/32':'against 64/32','against128/32':'against 128/32','CPUtime':'CPU time','walltime':'wall time'}.items():
        report_text=report_text.replace(old,new)
    t.core.write_record(report,report_text)

    t.save('completion.json',dict(completed_utc=t.core.utc(),official_games=80,remaining_games=0,
        no_extra_games=True,original67_preserved=True,final_audit_passed=True,
        selected_engine=t.load('STOCKBEAR_FINAL_CHAMPION.json')['selected_engine'],
        production_promoted=False,training=False,labeling=False,cleanup=False,
        output_sha256={name:t.core.sha(t.ROOT/name) for name in ['STOCKBEAR_GRAND_FINAL_REPORT.md','STOCKBEAR_FINAL_CHAMPION.json','analysis.json','final-audit.json','games.pgn','games.csv','moves.csv','resume-audit.json']}))
    manifest=t.load('manifest.json')
    for path in sorted(t.ROOT.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or 'artifacts' in path.parts or path.name=='manifest.json':
            continue
        data=path.read_bytes()
        manifest['files'][path.relative_to(t.ROOT).as_posix()]=dict(bytes=len(data),sha256=t.core.sha(path),lf_sha256=t.core.hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest())
    manifest['completed_utc']=t.core.utc()
    manifest['openings_sha256']=t.load('tournament-config.json')['openings_sha256']
    t.save('manifest.json',manifest)
    print(json.dumps(t.load('completion.json')),flush=True)


if __name__=='__main__':
    main()
