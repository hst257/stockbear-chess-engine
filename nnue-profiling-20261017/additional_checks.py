"""Short serial corroborating measurements; no alternative search or kernel."""
import json
import subprocess
import run_profile as p

config=p.common.load(p.ROOT/'build-components.json')
p.command(config['command'],p.ART/'components-build.log')
config['sha256']=p.common.sha(p.ART/'components.exe')
p.save('build-components-final.json',config)
p.pin()
varied=[]
for repeat in range(7):
    value=json.loads(subprocess.check_output([str(p.ART/'components.exe'),'--varied'],text=True))
    varied.append(dict(value,repeat=repeat))
p.save('varying-head.json',{'records':varied,'method':'Same production head; fixed seed legal walks, frames built before timing. Different sizes also change data footprint, so this does not isolate branch prediction from cache effects.'})
records=[]
rows=p.common.load(p.ROOT/'positions.json')
with p.engine('timers','classical') as player:
    for repeat in range(2):
        for row in rows:
            records.append(dict(p.checked_capture(player,row,'nodes',200000),repeat=repeat))
p.save('classical-timers.json',{'records':records,'method':'Clock-instrumented classical control, same FEN/history/options; exclusive times are biased, not production shares. Fresh TT/pawn cache each search.'})
print('Varying head and classical control complete',flush=True)
