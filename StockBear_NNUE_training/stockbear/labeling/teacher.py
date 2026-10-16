"""Bounded persistent UCI workers; the parent alone commits individual results."""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

import chess
import chess.engine

from ..common import digest, file_hash
from .storage import atomic_json, counts, get_meta, record_error, set_meta, utc


def options(cfg: dict, engine: chess.engine.SimpleEngine) -> dict:
    desired = {"Threads": cfg["threads"], "Hash": cfg["hash_mb"], "SyzygyPath": "",
               "UCI_LimitStrength": False, "Skill Level": 20}
    return {key: value for key,value in desired.items() if key in engine.options}


def launch(cfg: dict) -> chess.engine.SimpleEngine:
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
    engine = chess.engine.SimpleEngine.popen_uci(cfg["stockfish"], timeout=cfg["timeout"], **flags)
    try:
        if "stockfish" not in engine.id.get("name", "").casefold():
            raise ValueError("Teacher executable does not identify itself as Stockfish")
        engine.configure(options(cfg, engine))
        return engine
    except BaseException:
        engine.close()
        raise


def identify(cfg: dict, root: Path) -> tuple[dict, dict]:
    exe = Path(cfg["stockfish"])
    try:
        name = str(exe.relative_to(root))
    except ValueError:
        name = str(exe)
    # Exactly the existing v2 profile schema, including the version and counter convention.
    profile = {"executable": name, "sha256": file_hash(exe), "nodes": cfg["nodes"],
               "threads": cfg["threads"], "hash_mb": cfg["hash_mb"],
               "clear_hash_each_position": True, "mate_cp": 2000, "score_pov": "side_to_move",
               "counters": "0 1", "version": 2}
    with launch(cfg) as engine:
        info = {"id": engine.id, "configured_options": options(cfg,engine),
                "uci_defaults": {key: value.default for key,value in engine.options.items()},
                "multipv": 1, "analysis": "16384 nodes by default; new game clears hash per position",
                "python_chess": chess.__version__}
    return profile, info


def convert_score(score: chess.engine.Score) -> tuple[int, int | None]:
    raw = score.score(mate_score=32000)
    if raw is None:
        raise ValueError("Teacher supplied no finite centipawn/mate score")
    cp = (2000 if raw > 0 else -2000) if score.is_mate() else raw
    if not isinstance(cp,int) or abs(cp)>32000:
        raise ValueError(f"Out-of-range teacher cp: {cp}")
    return cp, score.mate()


class Workers:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.local = threading.local()
        self.engines: set[chess.engine.SimpleEngine] = set()
        self.lock = threading.Lock()

    def __call__(self, row: dict) -> dict:
        try:
            if getattr(self.local,"engine",None) is None:
                self.local.engine = launch(self.cfg)
                with self.lock:
                    self.engines.add(self.local.engine)
            board = chess.Board(row["fen"])
            if not board.is_valid() or board.is_game_over() or digest(row["fen"]) != row["id"]:
                raise ValueError("Invalid/corrupt queued position")
            # Same one-ucinewgame reset as ScaleWorker; no history/counters survive a position.
            info = self.local.engine.analyse(board,chess.engine.Limit(nodes=self.cfg["nodes"]),game=object())
            cp,mate = convert_score(info["score"].pov(board.turn))
            depth,nodes = info.get("depth"),info.get("nodes")
            if not isinstance(depth,int) or depth<1 or not isinstance(nodes,int) or nodes<1:
                raise ValueError("Missing/invalid teacher depth or node metadata")
            return {"cp":cp,"mate":mate,"depth":depth,"nodes":nodes,"error":None}
        except Exception as exc:
            engine = getattr(self.local,"engine",None)
            if engine is not None:
                engine.close()
                with self.lock:
                    self.engines.discard(engine)
                self.local.engine = None
            return {"cp":None,"mate":None,"depth":None,"nodes":None,
                    "error":f"{type(exc).__name__}: {exc}"[:4000]}

    def close(self) -> None:
        for engine in self.engines:
            try:
                engine.quit()
            except (chess.engine.EngineError,TimeoutError,OSError):
                engine.close()
        self.engines.clear()


def progress(db: sqlite3.Connection, directory: Path, state: str, start: float,
             initial_done: int, initial_elapsed: float) -> dict:
    result = counts(db)
    elapsed = time.monotonic()-start
    new = result["completed"]-initial_done
    rate = new/elapsed if elapsed>0 and new>0 else None
    result.update(utc=utc(),state=state,stage="labeling",session_new_labels=new,
                  session_elapsed_seconds=elapsed,total_labeling_seconds=initial_elapsed+elapsed,
                  positions_per_second=rate,eta_seconds=result["remaining"]/rate if rate else None,
                  sampling=get_meta(db,"sampling_report"))
    atomic_json(directory/"progress.json",result)
    eta = f"{result['eta_seconds']/3600:.2f}h" if result["eta_seconds"] is not None else "measuring"
    speed = f"{rate:.2f}/s" if rate else "measuring"
    print(f"{state}: {result['completed']:,}/{result['positions']:,} complete; "
          f"{result['remaining']:,} remaining ({result['failed']} failed); {speed}; "
          f"elapsed {elapsed/60:.1f}m; ETA {eta}",flush=True)
    with db:
        set_meta(db,"last_progress",result)
        set_meta(db,"labeling_seconds",initial_elapsed+elapsed)
    with (directory/"progress.log").open("a",encoding="utf-8") as stream:
        stream.write(json.dumps(result,sort_keys=True)+"\n")
    return result


def label(db: sqlite3.Connection, cfg: dict, directory: Path, retry_failed: bool = False,
          worker_factory=Workers) -> dict:
    profile = get_meta(db,"profile_id")
    with db:
        db.execute("INSERT OR IGNORE INTO labels(profile,id) SELECT ?,id FROM positions",(profile,))
        if retry_failed:
            db.execute("UPDATE labels SET failed=0,attempts=0 WHERE cp IS NULL AND failed=1")
            record_error(db,"manual-retry","","","Operator explicitly reset exhausted retry budgets; prior errors retained")
    start = last_tick = time.monotonic()
    initial = counts(db)["completed"]
    initial_elapsed = get_meta(db,"labeling_seconds") or 0
    worker = worker_factory(cfg)
    pool = ThreadPoolExecutor(max_workers=cfg["workers"])
    active = {}
    stopping, interrupted, consecutive_errors = False,False,0

    def save(future) -> None:
        nonlocal consecutive_errors,stopping
        row = active.pop(future)
        result = future.result()
        attempts = row["attempts"]+1
        failed = result["cp"] is None and attempts>=cfg["max_attempts"]
        with db:
            db.execute("UPDATE labels SET cp=?,mate=?,depth=?,nodes=?,attempts=?,error=?,failed=? "
                       "WHERE profile=? AND id=?",(result["cp"],result["mate"],result["depth"],result["nodes"],
                       attempts,result["error"],int(failed),profile,row["id"]))
            if result["error"]:
                record_error(db,"teacher","",row["id"],result["error"])
        consecutive_errors = consecutive_errors+1 if result["error"] else 0
        if consecutive_errors>=10:
            stopping = True

    try:
        progress(db,directory,"running",start,initial,initial_elapsed)
        while True:
            if not stopping:
                # At most workers outstanding. No giant executor queue, no persisted in-flight claims.
                rows = db.execute("SELECT p.id,p.fen,l.attempts FROM positions p JOIN labels l USING(id) "
                    "WHERE l.cp IS NULL AND l.failed=0 ORDER BY p.ordinal LIMIT ?",
                    (cfg["workers"]*2,)).fetchall()
                busy = {r["id"] for r in active.values()}
                for r in rows:
                    if len(active)>=cfg["workers"]:
                        break
                    if r["id"] not in busy:
                        active[pool.submit(worker,dict(r))] = dict(r)
            if not active:
                break
            finished,_ = wait(active,timeout=min(1,cfg["progress_seconds"]),return_when=FIRST_COMPLETED)
            for future in finished:
                save(future)
            if time.monotonic()-last_tick>=cfg["progress_seconds"]:
                progress(db,directory,"stopping" if stopping else "running",start,initial,initial_elapsed)
                last_tick = time.monotonic()
    except KeyboardInterrupt:
        interrupted = True
        print("Stopping after active analyses finish (bounded by the teacher timeout); committed labels are safe.",flush=True)
    finally:
        # Also persist already-submitted work on a normal Ctrl+C. A hard kill simply retries it on resume.
        try:
            for future in list(active):
                save(future)
        finally:
            pool.shutdown(wait=True,cancel_futures=True)
            worker.close()
    status = counts(db)
    state = "interrupted" if interrupted else "failed" if status["remaining"] else "complete"
    report = progress(db,directory,state,start,initial,initial_elapsed)
    if interrupted:
        raise KeyboardInterrupt
    if status["remaining"]:
        raise RuntimeError("Labeling incomplete: inspect errors; resume pending work or explicitly --retry-failed")
    return report
