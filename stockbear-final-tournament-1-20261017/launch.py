"""Hidden standalone launcher with process-state guard and preserved launch logs."""
import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys
import tournament as t


def state(handle):
    api=t.monitor.k.GetExitCodeProcess
    api.argtypes=[t.monitor.w.HANDLE,t.monitor.c.POINTER(t.monitor.w.DWORD)]
    exit_code=t.monitor.w.DWORD()
    assert api(handle,t.monitor.c.byref(exit_code))
    values=[t.monitor.w.FILETIME() for _ in range(4)]
    assert t.monitor.k.GetProcessTimes(handle,*[t.monitor.c.byref(x) for x in values])
    created=t.monitor.integer(values[0])
    when=dt.datetime(1601,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(microseconds=created//10)
    return exit_code.value,created,when.isoformat()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--probe-lifetime',action='store_true',help='Only launch a15-second idle file-writing smoke probe; no engines or tournament changes')
    args=parser.parse_args()
    flags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP
    if args.probe_lifetime:
        destination=t.ROOT/'smoke/launcher-lifetime.json'
        assert not destination.exists(),'Preserve existing probe receipt'
        code='import sys,time,json,os,datetime,pathlib; time.sleep(15); pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(passed=True,pid=os.getpid(),utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),engine_searches=0)))'
        process=subprocess.Popen([sys.executable,'-c',code,str(destination)],cwd=t.REPO,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            close_fds=True,creationflags=flags)
        print(f'Idle lifetime probe started: PID{process.pid}; no engines launched',flush=True)
        return
    path=t.ROOT/'runner-pid.json'
    if path.exists():
        old=t.core.load(path)
        handle=t.monitor.k.OpenProcess(0x1000,False,old['pid'])
        if handle:
            try:
                exit_code,created,when=state(handle)
                same=(created==old['creation_filetime']) if 'creation_filetime' in old else (
                    dt.datetime.fromisoformat(when)==dt.datetime.fromisoformat(old['started_utc']))
                if exit_code==259 and same:
                    raise RuntimeError('Existing runner is active; no second tournament started')
            finally:
                t.monitor.k.CloseHandle(handle)
    logs=t.ROOT/'run-logs'
    logs.mkdir(exist_ok=True)
    stamp=dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    stdout=logs/f'runner-{stamp}.log'
    stderr=logs/f'errors-{stamp}.log'
    command=[sys.executable,'-u',str(t.ROOT/'tournament.py'),'run']
    if args.resume:
        command.append('--resume')
    with stdout.open('ab',buffering=0) as out,stderr.open('ab',buffering=0) as err:
        process=subprocess.Popen(command,cwd=t.REPO,stdin=subprocess.DEVNULL,stdout=out,stderr=err,
                                 close_fds=True,creationflags=flags)
    handle=t.monitor.k.OpenProcess(0x1000,False,process.pid)
    assert handle
    try:
        _,created,when=state(handle)
    finally:
        t.monitor.k.CloseHandle(handle)
    t.save('runner-pid.json',dict(pid=process.pid,started_utc=when,creation_filetime=created,stdout=str(stdout),stderr=str(stderr),
                                 method='CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP; independently verified idle lifetime probe'))
    t.event('detached_launch',pid=process.pid,resume=args.resume)
    print(f'Detached tournament PID {process.pid}; resume={args.resume}',flush=True)


if __name__=='__main__':
    main()
