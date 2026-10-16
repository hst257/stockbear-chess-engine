"""Bounded, read-only live-queue/teacher diagnosis; never updates live labels."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "StockBear_NNUE_training"))

from stockbear.labeling.storage import atomic_json, connect, get_meta, source_hashes
from stockbear.labeling.teacher import Workers, launch

READY_SQL = """SELECT p.id,p.fen,l.attempts,p.ordinal FROM positions p
    CROSS JOIN labels l ON l.profile=? AND l.id=p.id
    WHERE p.ordinal>? AND l.cp IS NULL AND l.failed=0 ORDER BY p.ordinal LIMIT ?"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {"live_labels_modified": False, "native_analyses_limit": 96}
    with closing(connect(args.run/"pipeline.sqlite",readonly=True)) as db:
        cfg,profile = get_meta(db,"config"),get_meta(db,"profile_id")
        assert get_meta(db,"signature")["code"]==source_hashes()
        assert get_meta(db,"planned")
        report["config"] = cfg
        report["ready_plan"] = [list(r) for r in db.execute("EXPLAIN QUERY PLAN "+READY_SQL,(profile,0,64))]
        report["ready_seconds"] = []
        for _ in range(3):
            start = time.perf_counter()
            near = [dict(r) for r in db.execute(READY_SQL,(profile,0,12))]
            report["ready_seconds"].append(time.perf_counter()-start)
        maximum = db.execute("SELECT max(ordinal) FROM positions").fetchone()[0]
        chosen = {r["id"]:r for r in near}
        for i in range(36):
            offset = round((i+.5)*maximum/36)
            for row in db.execute(READY_SQL,(profile,offset,1)):
                chosen.setdefault(row["id"],dict(row))
        assert len(chosen)==48
        rows = list(chosen.values())
        report["positions"] = rows
        report["completed_before"] = [dict(r) for r in db.execute("SELECT * FROM labels WHERE cp IS NOT NULL ORDER BY id")]
        for row in rows:
            assert db.execute("SELECT cp,failed FROM labels WHERE profile=? AND id=?",(profile,row["id"])).fetchone()[0] is None
    report["worker_trials"] = []
    for workers in (2,4):
        worker = Workers(cfg)
        barrier = threading.Barrier(workers+1)
        service = []
        lock = threading.Lock()

        def initialize() -> None:
            engine = launch(cfg)
            worker.local.engine = engine
            with worker.lock:
                worker.engines.add(engine)
            original = engine.analyse
            def timed_analyse(*a,**kw):
                start = time.perf_counter()
                info = original(*a,**kw)
                worker.local.last_analysis = {"analyse_seconds":time.perf_counter()-start,
                    "engine_seconds":info.get("time"),"engine_nps":info.get("nps")}
                return info
            engine.analyse = timed_analyse
            barrier.wait(timeout=60)

        def evaluate(row: dict) -> dict:
            start = time.perf_counter()
            result = worker(row)
            assert result["error"] is None,result
            result.update(id=row["id"],ordinal=row["ordinal"],service_seconds=time.perf_counter()-start,
                          **worker.local.last_analysis)
            with lock:
                service.append(result)
            return result
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                initialization = [pool.submit(initialize) for _ in range(workers)]
                barrier.wait(timeout=60)
                for f in initialization: f.result()
                start = time.perf_counter()
                list(pool.map(evaluate,rows))
                elapsed = time.perf_counter()-start
        finally:
            worker.close()
        trial = {"workers":workers,"threads_each":cfg["threads"],"positions":len(rows),
            "wall_seconds":elapsed,"positions_per_second":len(rows)/elapsed,
            "mean_service_seconds":statistics.mean(r["service_seconds"] for r in service),
            "median_service_seconds":statistics.median(r["service_seconds"] for r in service),
            "mean_analyse_seconds":statistics.mean(r["analyse_seconds"] for r in service),
            "mean_engine_seconds":statistics.mean(r["engine_seconds"] for r in service),
            "mean_actual_nodes":statistics.mean(r["nodes"] for r in service),
            "results":sorted(service,key=lambda r:r["ordinal"])}
        report["worker_trials"].append(trial)
        atomic_json(args.output.with_suffix(".progress.json"),report)
        print(json.dumps({k:v for k,v in trial.items() if k!="results"}),flush=True)
    a,b = report["worker_trials"]
    report["two_four_exact_labels"] = all(tuple(x[k] for k in ("id","cp","mate","depth","nodes"))==
        tuple(y[k] for k in ("id","cp","mate","depth","nodes")) for x,y in zip(a["results"],b["results"]))
    assert report["two_four_exact_labels"]
    with closing(connect(args.run/"pipeline.sqlite",readonly=True)) as db:
        assert report["completed_before"]==[dict(r) for r in db.execute("SELECT * FROM labels WHERE cp IS NOT NULL ORDER BY id")]
        for row in rows:
            actual = db.execute("SELECT cp,attempts FROM labels WHERE profile=? AND id=?",(profile,row["id"])).fetchone()
            assert actual["cp"] is None and actual["attempts"]==row["attempts"]
    report["native_analyses"] = 96
    report["completed_labels_unchanged"] = True
    report["pending_labels_and_attempts_unchanged"] = True
    report["four_two_throughput_ratio"] = b["positions_per_second"]/a["positions_per_second"]
    atomic_json(args.output,report)


if __name__=="__main__":
    main()
