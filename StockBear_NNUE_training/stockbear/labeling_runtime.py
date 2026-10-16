"""Compatible fast scheduler for already-ingested labeling runs.

The signed v1 modules, teacher, configuration and queue remain unchanged. This
separately identified runner changes only work retrieval and progress accounting.
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from .labeling import __main__ as original
from .labeling.storage import atomic_json, connect, counts, get_meta, record_error, set_meta, utc, writer_lock
from .labeling.teacher import Workers

# CROSS JOIN deliberately keeps the ordinal range scan outside indexed label lookups.
# An ordinary JOIN let SQLite scan/sort millions of labels for every tiny batch.
READY_SQL = """SELECT p.id,p.fen,l.attempts,p.ordinal FROM positions p
    CROSS JOIN labels l ON l.profile=? AND l.id=p.id
    WHERE p.ordinal>? AND l.cp IS NULL AND l.failed=0
    ORDER BY p.ordinal LIMIT ?"""


def execution_workers(cfg: dict, override: int | None) -> int:
    workers = cfg["workers"] if override is None else override
    if not 1<=workers<=8 or workers*cfg["threads"]>max(1,(os.cpu_count() or 2)//2):
        raise ValueError("Execution worker count exceeds the existing conservative CPU cap")
    if workers*cfg["hash_mb"]>4096:
        raise ValueError("Execution hash allocation exceeds 4096 MiB")
    return workers


def require_ingested(db: sqlite3.Connection, cfg: dict, sources: list[dict]) -> None:
    if not get_meta(db,"planned") or db.execute("SELECT 1 FROM sources WHERE complete=0 LIMIT 1").fetchone():
        raise ValueError("Fast resume requires a completely ingested and already-planned queue")


def require_planned(db: sqlite3.Connection, cfg: dict, aliases: list[str]) -> None:
    if not get_meta(db,"planned"):
        raise ValueError("Fast resume never rebuilds an ingestion queue")


def runtime_identity(cfg: dict, workers: int, signature: dict | None) -> dict:
    return {"runner":"stockbear.labeling_runtime","version":1,
        "source_lf_sha256":hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
        "saved_signature_sha256":hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest(),
        "saved_workers":cfg["workers"],"execution_workers":workers,"threads_each":cfg["threads"],
        "teacher_options_changed":False,"queue":"ordinal keyset with bounded local retry buffer",
        "progress":"initial authoritative counts plus committed changes; final SQL reconciliation"}


def label_fast(db: sqlite3.Connection, cfg: dict, directory: Path, retry_failed: bool = False,
               worker_factory=Workers, *, workers: int | None = None) -> dict:
    selected_workers = execution_workers(cfg,workers)
    work_cfg = dict(cfg,workers=selected_workers)
    profile = get_meta(db,"profile_id")
    timings = {key:0.0 for key in ("initialization_seconds","queue_seconds","update_seconds",
                                  "commit_seconds","progress_seconds","wait_seconds","final_count_seconds")}
    queue_calls = 0
    before = time.perf_counter()
    with db:
        # Do not rescan/reseed an already initialized multi-million-row label table.
        position_count = db.execute("SELECT count(*) FROM positions").fetchone()[0]
        label_count = db.execute("SELECT count(*) FROM labels WHERE profile=?",(profile,)).fetchone()[0]
        if position_count!=label_count:
            db.execute("INSERT OR IGNORE INTO labels(profile,id) SELECT ?,id FROM positions",(profile,))
        if retry_failed:
            db.execute("UPDATE labels SET failed=0,attempts=0 WHERE cp IS NULL AND failed=1")
            record_error(db,"manual-retry","","","Operator reset exhausted retry budgets; errors retained")
    state = counts(db)
    timings["initialization_seconds"] = time.perf_counter()-before
    initial_done = state["completed"]
    initial_elapsed = get_meta(db,"labeling_seconds") or 0
    identity = runtime_identity(cfg,selected_workers,get_meta(db,"signature"))
    atomic_json(directory/"fast-runtime.json",identity)
    worker = worker_factory(work_cfg)
    pool = ThreadPoolExecutor(max_workers=selected_workers)
    buffer = deque()
    active = {}
    cursor,exhausted = 0,False
    stopping,interrupted,consecutive_errors = False,False,0
    start = last_tick = time.monotonic()

    def progress(status: str) -> dict:
        before = time.perf_counter()
        elapsed = time.monotonic()-start
        new = state["completed"]-initial_done
        rate = new/elapsed if elapsed>0 and new>0 else None
        result = dict(state,utc=utc(),state=status,stage="labeling",session_new_labels=new,
            session_elapsed_seconds=elapsed,total_labeling_seconds=initial_elapsed+elapsed,
            positions_per_second=rate,eta_seconds=state["remaining"]/rate if rate else None,
            sampling=get_meta(db,"sampling_report"),execution=identity,timings=dict(timings),queue_calls=queue_calls)
        atomic_json(directory/"progress.json",result)
        with db:
            set_meta(db,"last_progress",result)
            set_meta(db,"labeling_seconds",initial_elapsed+elapsed)
        with (directory/"progress.log").open("a",encoding="utf-8") as stream:
            stream.write(json.dumps(result,sort_keys=True)+"\n")
        speed = f"{rate:.2f}/s" if rate else "measuring"
        eta = f"{result['eta_seconds']/3600:.2f}h" if rate else "measuring"
        print(f"{status}: {state['completed']:,}/{state['positions']:,} complete; "
              f"{state['remaining']:,} remaining ({state['failed']} failed); {speed}; "
              f"elapsed {elapsed/60:.1f}m; ETA {eta}; {selected_workers} workers",flush=True)
        timings["progress_seconds"] += time.perf_counter()-before
        return result

    def save(future) -> None:
        nonlocal stopping,consecutive_errors
        row = active.pop(future)
        result = future.result()
        attempts = row["attempts"]+1
        failed = result["cp"] is None and attempts>=cfg["max_attempts"]
        before = time.perf_counter()
        try:
            db.execute("UPDATE labels SET cp=?,mate=?,depth=?,nodes=?,attempts=?,error=?,failed=? "
                "WHERE profile=? AND id=?",(result["cp"],result["mate"],result["depth"],result["nodes"],
                attempts,result["error"],int(failed),profile,row["id"]))
            if result["error"]:
                record_error(db,"teacher","",row["id"],result["error"])
            timings["update_seconds"] += time.perf_counter()-before
            before = time.perf_counter()
            db.commit()  # Retain one FULL-synchronous durable transaction per result.
            timings["commit_seconds"] += time.perf_counter()-before
        except BaseException:
            db.rollback()
            raise
        state["attempts"] += 1
        if result["error"]:
            state["errors"] += 1
        if result["cp"] is not None:
            state["completed"] += 1
        elif failed:
            state["failed"] += 1
        else:
            # Retry locally even though the scan cursor has already passed this row.
            buffer.append(dict(row,attempts=attempts))
        state["remaining"] = state["positions"]-state["completed"]
        state["pending"] = state["remaining"]-state["failed"]
        consecutive_errors = consecutive_errors+1 if result["error"] else 0
        stopping |= consecutive_errors>=10

    try:
        progress("running")
        while True:
            if not stopping:
                while len(active)<selected_workers:
                    if not buffer and not exhausted:
                        before = time.perf_counter()
                        rows = db.execute(READY_SQL,(profile,cursor,max(32,selected_workers*16))).fetchall()
                        timings["queue_seconds"] += time.perf_counter()-before
                        queue_calls += 1
                        if rows:
                            cursor = rows[-1]["ordinal"]
                            buffer.extend(dict(row) for row in rows)
                        else:
                            exhausted = True
                    if not buffer:
                        break
                    row = buffer.popleft()
                    active[pool.submit(worker,row)] = row
            if not active:
                break
            before = time.perf_counter()
            finished,_ = wait(active,timeout=min(1,cfg["progress_seconds"]),return_when=FIRST_COMPLETED)
            timings["wait_seconds"] += time.perf_counter()-before
            for future in finished:
                save(future)
            if time.monotonic()-last_tick>=cfg["progress_seconds"]:
                progress("stopping" if stopping else "running")
                last_tick = time.monotonic()
    except KeyboardInterrupt:
        interrupted = True
        print("Stopping after active analyses finish; committed labels and the original queue are safe.",flush=True)
    finally:
        try:
            for future in list(active):
                save(future)
        finally:
            pool.shutdown(wait=True,cancel_futures=True)
            worker.close()
    before = time.perf_counter()
    authoritative = counts(db)
    timings["final_count_seconds"] = time.perf_counter()-before
    if state!=authoritative:
        raise RuntimeError("Progress counter reconciliation failed; committed SQL state remains authoritative")
    status = "interrupted" if interrupted else "failed" if state["remaining"] else "complete"
    report = progress(status)
    if interrupted:
        raise KeyboardInterrupt
    if state["remaining"]:
        raise RuntimeError("Labeling incomplete; resume pending work or explicitly --retry-failed")
    return report


def main() -> int:
    extra = argparse.ArgumentParser(add_help=False)
    extra.add_argument("--execution-workers",type=int)
    extra.add_argument("--check-resume",action="store_true")
    execution,remaining = extra.parse_known_args()
    args = original.parser().parse_args(remaining)
    try:
        if args.action!="run" or not args.resume:
            raise ValueError("Fast resume requires run --resume and an existing planned queue")
        directory = args.output.resolve()
        if not (directory/"pipeline.sqlite").is_file():
            raise ValueError("No existing pipeline database")
        # Preflight is read-only except the existing OS writer lock. It never runs workers.
        with writer_lock(directory),closing(connect(directory/"pipeline.sqlite",readonly=True)) as db:
            saved = get_meta(db,"config")
            cfg = original.configuration(args,saved)
            original.output_guard(directory,cfg)
            original.check_signature(get_meta(db,"signature"),cfg)
            require_ingested(db,cfg,[])
            workers = execution_workers(cfg,execution.execution_workers)
            if execution.check_resume:
                print(json.dumps({"safe_to_resume":True,"queue_rebuild":False,"workers_started":False,
                    "signature_unchanged":True,"execution":runtime_identity(cfg,workers,get_meta(db,"signature"))},indent=2))
                return 0
        # The original guard still verifies all signed files, inputs, runtime and teacher.
        original.ingest = require_ingested
        original.finalize = require_planned
        original.label = lambda db,cfg,path,retry: label_fast(db,cfg,path,retry,workers=workers)
        original.execute(args)
        return 0
    except KeyboardInterrupt:
        print("Interrupted safely; use the same fast-resume command.",file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
