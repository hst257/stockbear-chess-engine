"""Run declared variants serially; numerical failures never reach benchmarking."""
import subprocess
import sys
import experiment as p

for label in ['unroll4','hiddenclip']:
    if (p.ROOT/('trial-'+label+'.json')).exists():
        print('Completed trial exists; skipping',label,flush=True)
        continue
    if (p.ROOT/('failure-'+label+'.json')).exists():
        print('Failed frozen candidate exists; inspect receipt rather than retrying',label,flush=True)
        continue
    phase='build'
    try:
        if not all((p.ROOT/f'build-{label}-{target}.json').exists() for target in ['engine','micro','oracle']):
            p.build(label)
        phase='bitwise and fixed-work correctness'
        if not (p.ROOT/('correctness-'+label+'.json')).exists():p.correctness(label)
        phase='interruption, terminals and fallback'
        if not (p.ROOT/('regressions-'+label+'.json')).exists():
            subprocess.run([sys.executable,str(p.ROOT/'regressions.py'),label],check=True)
        phase='internal restoration'
        if not (p.ROOT/('build-restoration-'+label+'.json')).exists():
            subprocess.run([sys.executable,str(p.ROOT/'restoration_observer.py'),label],check=True)
        if not (p.ROOT/('regressions-restore-'+label+'.json')).exists():
            subprocess.run([sys.executable,str(p.ROOT/'regressions.py'),'restore-'+label],check=True)
        phase='assembly'
        if not (p.ROOT/('head-inspection-'+label+'.json')).exists():
            subprocess.run([sys.executable,str(p.ROOT/'inspect_head.py'),label],check=True)
        phase='representative inference microbenchmarks'
        if not (p.ROOT/('micro-'+label+'.json')).exists():p.micro(label)
        phase='whole-engine benchmark'
        p.search(label)
        p.save('trial-'+label+'.json',dict(completed=True,correctness_passed=True,performance_complete=True))
    except Exception as error:
        p.save('failure-'+label+'.json',dict(phase=phase,error=str(error),
            benchmark_allowed=False if phase in ['build','bitwise and fixed-work correctness'] else None))
        if phase in ['build','bitwise and fixed-work correctness','interruption, terminals and fallback','internal restoration']:
            print('Stopping failed candidate',label,phase,str(error),flush=True)
            continue
        raise
