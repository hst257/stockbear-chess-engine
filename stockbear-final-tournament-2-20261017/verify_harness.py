"""Excluded, bounded checkpoint/resume and report-dispatch verification."""
from pathlib import Path
import subprocess
import sys
import tournament as t


def main():
    official=t.ROOT
    assert not t.completed()
    t.monitor.pin()
    config=t.config_check()
    # Report is the correct local script and refuses incomplete data without playing.
    proc=subprocess.run([sys.executable,str(official/'analyze.py')],cwd=t.REPO,capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert proc.returncode!=0 and 'Tournament incomplete' in proc.stderr,proc.stderr
    assert not t.completed()
    t.core.write_record(official/'smoke/report-incomplete-check.log',proc.stderr)
    smoke=official/'smoke/resume-harness'
    smoke.mkdir(exist_ok=False)
    for name in ['opening-suite.json','schedule.json','environment.json']:
        t.shutil.copy2(official/name,smoke/name)
    config['max_searched_plies']=4
    t.core.save(smoke/'tournament-config.json',config)
    t.ROOT=smoke
    game=t.load('schedule.json')[0]
    real_save=t.core.save
    interrupted=False
    def interrupt(path,value):
        nonlocal interrupted
        real_save(path,value)
        if not interrupted and str(path).endswith('.partial.json') and len(value.get('searches',[]))==2:
            interrupted=True
            raise KeyboardInterrupt('Deliberate excluded smoke interrupt')
    t.core.save=interrupt
    try:
        t.play(game,config,[])
        raise AssertionError('Expected deliberate interruption')
    except KeyboardInterrupt:
        pass
    finally:
        t.core.save=real_save
    before=t.core.load(smoke/'games/G001.partial.json')
    assert len(before['searches'])==2
    row=t.play(game,config,[])
    assert row['resumptions']==1 and row['searches'][:2]==before['searches']
    assert len(row['searches'])==4 and row['termination']=='adjudicated_maximum_ply_draw'
    assert row['complete'] and len(t.completed())==1
    # Four searches total, not six; completed game selection never executes play again.
    commands=[]
    for path in (smoke/'logs/G001').glob('*.log'):
        commands.extend(line.split(' > ',1)[1] for line in path.read_text().splitlines() if ' > go ' in line)
    assert commands==['go movetime 500']*4,commands
    t.ROOT=official
    assert not t.completed()
    for rel,digest in t.load('preservation-before.json').items():
        assert t.core.sha(t.REPO/rel)==digest,rel
    receipt=dict(passed=True,excluded=True,smoke_searches=4,saved_searches_preserved=2,partial_resumptions=1,go_commands=4,
                 report_dispatch='Explicit local analyzer rejected incomplete80 before any engine/search',production_unchanged=True)
    t.save('smoke/harness-verification.json',receipt)
    preflight=t.load('preflight.json')
    preflight['genuine_resume_smoke']=receipt
    t.save('preflight.json',preflight)
    t.save('runner-lock.json',t.code_hashes())
    print('Excluded resume smoke passed:2 searches saved,2 additional,zero replay; report dispatch passed',flush=True)


if __name__=='__main__':
    main()
