"""Replay measured pending results in small disposable databases, not the live run."""
from __future__ import annotations

from contextlib import closing
import argparse
import json
from pathlib import Path
import re
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"StockBear_NNUE_training"))
from stockbear.labeling.storage import atomic_json,connect,get_meta,initialize,set_meta
from stockbear.labeling_runtime import label_fast

ART=ROOT/"artifacts/labeling/performance-20261016"
RUN=ROOT/"StockBear_NNUE_training/data/labeling/cc-events-v1"


def clone(path: Path,ids: list[str]) -> dict:
    if path.exists(): raise FileExistsError(path)
    path.mkdir()
    with closing(connect(RUN/"pipeline.sqlite",readonly=True)) as source,closing(connect(path/"pipeline.sqlite")) as target:
        initialize(target)
        with target:
            for key in ("config","signature","profile_id","profile","teacher","planned"):
                set_meta(target,key,get_meta(source,key))
            set_meta(target,"sampling_report",{"diagnostic_shadow_positions":len(ids),"live_queue_unchanged":True})
            for table in ("sources","games","groups","positions"):
                if table=="sources": rows=source.execute("SELECT * FROM sources").fetchall()
                elif table=="games":
                    owners=[source.execute("SELECT owner FROM positions WHERE id=?",(pid,)).fetchone()[0] for pid in ids]
                    rows=[source.execute("SELECT * FROM games WHERE id=?",(gid,)).fetchone() for gid in sorted(set(owners))]
                elif table=="groups":
                    groups=[source.execute("SELECT game_id FROM positions WHERE id=?",(pid,)).fetchone()[0] for pid in ids]
                    rows=[source.execute("SELECT * FROM groups WHERE id=?",(gid,)).fetchone() for gid in sorted(set(groups))]
                else: rows=[source.execute("SELECT * FROM positions WHERE id=?",(pid,)).fetchone() for pid in ids]
                for row in rows:
                    target.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})",tuple(row))
            profile=get_meta(source,"profile_id")
            for pid in ids:
                row=source.execute("SELECT * FROM labels WHERE profile=? AND id=?",(profile,pid)).fetchone()
                assert row["cp"] is None
                target.execute("INSERT INTO labels VALUES (?,?,?,?,?,?,?,?,?)",tuple(row))
        return get_meta(source,"config")


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag",default="")
    args=parser.parse_args()
    if args.tag and not re.fullmatch("[a-z0-9-]+",args.tag):raise ValueError("Invalid output tag")
    suffix="-"+args.tag if args.tag else ""
    native=json.loads((ART/"native.json").read_text())
    output=ART/f"database-replay{suffix}.json"
    if output.exists():raise FileExistsError(output)
    trials=[]
    for trial in native["worker_trials"]:
        rows={r["id"]:r for r in trial["results"]}
        path=ART/f"replay{suffix}-{trial['workers']}"
        cfg=clone(path,list(rows))
        class Replay:
            def __init__(self,cfg):pass
            def __call__(self,row):
                saved=rows[row["id"]]
                time.sleep(saved["service_seconds"])
                return {k:saved[k] for k in ("cp","mate","depth","nodes","error")}
            def close(self):pass
        with closing(connect(path/"pipeline.sqlite")) as db:
            result=label_fast(db,cfg,path,workers=trial["workers"],worker_factory=Replay)
            assert result["completed"]==48 and result["remaining"]==0
            trials.append({"workers":trial["workers"],"result":result})
    probe=ART/f"commit-probe{suffix}.sqlite"
    if probe.exists():raise FileExistsError(probe)
    timings=[];updates=[]
    with closing(connect(probe)) as db:
        db.execute("CREATE TABLE labels(profile TEXT,id TEXT,cp INTEGER,attempts INTEGER,PRIMARY KEY(profile,id))")
        db.executemany("INSERT INTO labels VALUES (?,?,?,?)",[("profile",str(i),0,0) for i in range(4096)])
        db.commit()
        for i in range(1024):
            start=time.perf_counter()
            db.execute("UPDATE labels SET cp=cp+1,attempts=attempts+1 WHERE profile=? AND id=?",("profile",str(i)))
            updates.append(time.perf_counter()-start)
            start=time.perf_counter();db.commit();timings.append(time.perf_counter()-start)
        pragmas={key:db.execute("PRAGMA "+key).fetchone()[0] for key in ("journal_mode","synchronous","wal_autocheckpoint")}
    sorted_times=sorted(timings)
    result={"method":"Measured native service durations replayed as sleeps in disposable 48-row shadow databases. Not additional Stockfish analyses or a sustained live throughput benchmark. Small scratch B-trees do not model every live page-cache/checkpoint cost.",
        "live_database_modified":False,"additional_stockfish_analyses":0,"trials":trials,
        "commit_probe":{"updates":1024,"mean_update_seconds":statistics.mean(updates),
            "mean_commit_seconds":statistics.mean(timings),"median_commit_seconds":statistics.median(timings),
            "p95_commit_seconds":sorted_times[972],"p99_commit_seconds":sorted_times[1013],
            "max_commit_seconds":max(timings),"pragmas":pragmas}}
    atomic_json(output,result)
    print(json.dumps({"replay_rates":{str(t['workers']):t['result']['positions_per_second'] for t in trials},"commit_probe":result['commit_probe']},indent=2))


if __name__=="__main__":main()
