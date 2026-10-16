"""Compare 4/8 teacher workers on 48 pending positions without persisting labels."""
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
sys.path.insert(0,str(ROOT/"StockBear_NNUE_training"))

from stockbear.labeling import __main__ as original
from stockbear.labeling.storage import atomic_json, connect, counts, get_meta, utc, writer_lock
from stockbear.labeling.teacher import Workers, launch
from stockbear.labeling_runtime import READY_SQL, execution_workers, require_ingested, runtime_identity


def trial(cfg: dict, rows: list[dict], workers: int) -> dict:
    execution_workers(cfg,workers)
    teacher = Workers(dict(cfg,workers=workers))
    ready = threading.Barrier(workers+1)

    def initialize() -> None:
        try:
            engine = launch(teacher.cfg)
            teacher.local.engine = engine
            with teacher.lock:
                teacher.engines.add(engine)
            ready.wait(timeout=20)
        except BaseException:
            ready.abort()
            raise

    def evaluate(row: dict) -> dict:
        started = time.perf_counter()
        result = teacher(row)
        if result["error"]:
            raise RuntimeError(result["error"])
        return dict(result,id=row["id"],service_seconds=time.perf_counter()-started)

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            initialized = [pool.submit(initialize) for _ in range(workers)]
            ready.wait(timeout=20)
            for future in initialized:
                future.result()
            started = time.perf_counter()
            results = list(pool.map(evaluate,rows))
            elapsed = time.perf_counter()-started
    finally:
        teacher.close()
    return dict(workers=workers,threads_each=cfg["threads"],positions=len(rows),
                wall_seconds=elapsed,positions_per_second=len(rows)/elapsed,
                mean_service_seconds=statistics.mean(r["service_seconds"] for r in results),
                mean_actual_nodes=statistics.mean(r["nodes"] for r in results),results=results)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    directory = args.run.resolve()
    original.output_guard(args.output.resolve())
    if args.output.resolve().is_relative_to(directory):
        raise ValueError("Keep benchmark results outside the preserved live run directory")
    if args.output.exists():
        raise FileExistsError(args.output)
    database = directory/"pipeline.sqlite"
    # Hold the same writer lock as production; refuse an active run rather than compete.
    with writer_lock(directory),closing(connect(database,readonly=True)) as db:
        cfg,signature = get_meta(db,"config"),get_meta(db,"signature")
        original.check_signature(signature,cfg)
        require_ingested(db,cfg,[])
        execution_workers(cfg,8)
        profile = get_meta(db,"profile_id")
        before = counts(db)
        data_version = db.execute("PRAGMA data_version").fetchone()[0]
        progress_path = directory/"progress.json"
        progress_sha = sha(progress_path)
        near = [dict(r) for r in db.execute(READY_SQL,(profile,0,12))]
        if len(near)!=12:
            raise ValueError("At least 48 pending positions are required for this comparison")
        maximum = db.execute("SELECT max(ordinal) FROM positions").fetchone()[0]
        start = near[-1]["ordinal"]
        selected = {row["id"]:row for row in near}
        for i in range(36):
            cursor = start+round((i+.5)*(maximum-start)/36)
            for row in db.execute(READY_SQL,(profile,cursor,1)):
                selected.setdefault(row["id"],dict(row))
        if len(selected)!=48:
            raise ValueError("Could not select 48 distinct pending positions")
        rows = list(selected.values())
        originals = [tuple(db.execute("SELECT * FROM labels WHERE profile=? AND id=?",
                                     (profile,row["id"])).fetchone()) for row in rows]
        last = get_meta(db,"last_progress")
        report = dict(utc=utc(),native_analyses_limit=96,live_database_open_mode="read-only",
                      config=cfg,profile_id=profile,before=before,prior_progress=last,
                      execution=runtime_identity(cfg,8,signature),positions=rows,trials=[])
        for workers in (4,8):
            result = trial(cfg,rows,workers)
            report["trials"].append(result)
            print(json.dumps({k:v for k,v in result.items() if k!="results"}),flush=True)
        four,eight = report["trials"]
        keys = ("id","cp","mate","depth","nodes")
        report["exact_labels"] = all(tuple(a[k] for k in keys)==tuple(b[k] for k in keys)
                                     for a,b in zip(four["results"],eight["results"]))
        assert report["exact_labels"]
        after = counts(db)
        assert before==after
        assert data_version==db.execute("PRAGMA data_version").fetchone()[0]
        assert originals==[tuple(db.execute("SELECT * FROM labels WHERE profile=? AND id=?",
                                           (profile,row["id"])).fetchone()) for row in rows]
        assert get_meta(db,"config")==cfg and get_meta(db,"signature")==signature
        assert sha(progress_path)==progress_sha
        report.update(after=after,native_analyses=96,persisted_labels_unchanged=True,
                      progress_unchanged=True,signature_unchanged=True,
                      eight_four_ratio=eight["positions_per_second"]/four["positions_per_second"],
                      limitation="48 positions per worker count; warm search only, sequential 4 then 8. Not a sustained thermal or database-write benchmark.")
        atomic_json(args.output,report)
        print(json.dumps({"eight_four_ratio":report["eight_four_ratio"],
                          "live_labels_unchanged":True,"native_analyses":96}),flush=True)


if __name__=="__main__":
    main()
