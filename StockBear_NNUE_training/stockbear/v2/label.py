from __future__ import annotations

import concurrent.futures
import json
import time
from pathlib import Path

import chess
import chess.engine
import psutil

from ..common import connect, digest, metadata, save_json
from ..teacher import Worker, find_teacher, teacher_profile


class ScaleWorker(Worker):
    """One Stockfish search_clear via ucinewgame, instead of two identical clears.

    Both commands call Engine::search_clear in the downloaded Stockfish source.
    Cache compatibility is additionally tested against the unchanged v1 worker.
    """
    def __call__(self, row):
        pid, fen, previous_attempts = row
        error = None
        for attempt in range(previous_attempts,3):
            try:
                board=chess.Board(fen)
                if not board.is_valid() or digest(fen)!=pid:
                    return pid,None,None,None,None,3,"corrupt/illegal canonical position"
                engine=self.engine()
                info=engine.analyse(board,chess.engine.Limit(nodes=self.profile["nodes"]),game=object())
                score=info["score"].pov(board.turn)
                raw=score.score(mate_score=32000)
                cp=(2000 if raw>0 else -2000) if score.is_mate() else raw
                return pid,cp,score.mate(),info.get("depth"),info.get("nodes"),attempt+1,None
            except (chess.engine.EngineError,TimeoutError,OSError) as exc:
                error=f"{type(exc).__name__}: {exc}"[:1000]
                engine=getattr(self.local,"engine",None)
                if engine:
                    try: engine.close()
                    except Exception: pass
                self.local.engine=None
        return pid,None,None,None,None,3,error


def setup(root,cfg):
    db=connect(root/cfg["cache"])
    db.execute("""CREATE TABLE IF NOT EXISTS labels(profile TEXT,id TEXT,cp INTEGER,mate INTEGER,
        depth INTEGER,nodes INTEGER,attempts INTEGER NOT NULL,error TEXT,PRIMARY KEY(profile,id))""")
    profile=teacher_profile(root,cfg)
    profile_id=digest(json.dumps(profile,sort_keys=True))
    metadata(db,f"profile:{profile_id}",profile)
    if not metadata(db,"v1_imported"):
        db.execute("ATTACH DATABASE ? AS original",(str(root/"data/cache/teacher.sqlite"),))
        db.execute("INSERT OR IGNORE INTO labels SELECT * FROM original.labels WHERE profile=?",(profile_id,))
        db.commit()
        count=db.execute("SELECT count(*) FROM labels WHERE profile=?",(profile_id,)).fetchone()[0]
        metadata(db,"v1_imported",{"profile":profile_id,"rows":count})
    db.execute("ATTACH DATABASE ? AS pool",(str(root/cfg["pool"]),))
    return db,profile,profile_id


def benchmark(root:Path,cfg:dict):
    db,profile,profile_id=setup(root,cfg)
    old=connect(root/"data/cache/teacher.sqlite")
    old.execute("ATTACH DATABASE ? AS corpus",(str(root/"data/processed/full.sqlite"),))
    reference=old.execute("SELECT p.id,p.fen,l.cp,l.mate,l.depth,l.nodes FROM corpus.positions p JOIN labels l USING(id) WHERE l.profile=? ORDER BY p.id LIMIT 64",(profile_id,)).fetchall()
    worker=ScaleWorker(find_teacher(root),profile)
    try:
        for pid,fen,cp,mate,depth,nodes in reference:
            actual=worker((pid,fen,0))
            if actual[1:5]!=(cp,mate,depth,nodes): raise AssertionError(f"v1 reset/cache mismatch: {pid}")
    finally: worker.close(); old.close()
    rows=db.execute("SELECT id,fen,0 FROM pool.positions ORDER BY ordinal LIMIT 1024").fetchall()
    trials=[]
    for workers in (4,6):
        worker=ScaleWorker(find_teacher(root),profile)
        psutil.cpu_percent(None)
        start=time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(workers) as executor:
            labels=list(executor.map(worker,rows))
        seconds=time.monotonic()-start
        cpu=psutil.cpu_percent(None)
        process_cpu=sum(sum(psutil.Process(engine.transport.get_pid()).cpu_times()[:2]) for engine in worker.engines)
        worker.close()
        if any(row[1] is None for row in labels): raise RuntimeError("Teacher benchmark failure")
        db.executemany("INSERT OR IGNORE INTO labels VALUES (?,?,?,?,?,?,?,?)",[(profile_id,*row) for row in labels])
        db.commit()
        trial={"workers":workers,"positions":len(rows),"seconds":seconds,"positions_per_second":len(rows)/seconds,
               "system_cpu_percent":cpu,"teacher_cpu_percent_one_core_100":100*process_cpu/seconds}
        trials.append(trial)
        print(f"Label benchmark: {trial}",flush=True)
    chosen=trials[1] if trials[1]["positions_per_second"]>trials[0]["positions_per_second"]*1.10 else trials[0]
    count=db.execute("SELECT count(*) FROM pool.positions").fetchone()[0]
    target=min(cfg["largest_target"],count)
    estimated=target/chosen["positions_per_second"]
    if estimated>cfg["label_budget_hours"]*3600:
        target=min(target,int(cfg["label_budget_hours"]*3600*chosen["positions_per_second"]))
    report={"trials":trials,"selected_workers":chosen["workers"],"profile":profile,"profile_id":profile_id,
            "cache_reset_exact_positions":len(reference),"largest_practical":target,"estimated_label_hours":estimated/3600,
            "estimated_sqlite_bytes":target*450,"estimated_prepared_bytes":target*180,
            "bounded_budget_hours":cfg["label_budget_hours"],"other_engine_experiments_present":False,
            "reset_optimization":"one ucinewgame search_clear; redundant Clear Hash removed after exact parity"}
    save_json(root/cfg["reports"]/"label_benchmark.json",report)
    db.close()
    return report


def label(root:Path,cfg:dict,size:int,limit:int|None=None):
    db,profile,profile_id=setup(root,cfg)
    bench=json.loads((root/cfg["reports"]/"label_benchmark.json").read_text())
    if size>bench["largest_practical"]: raise ValueError("Requested label count exceeds benchmarked bound")
    cursor_key=f"cursor:{profile_id}"
    cursor=metadata(db,cursor_key) or 0
    # A smaller earlier dataset can be requested after a larger one finished.
    cursor=min(cursor,size)
    worker=ScaleWorker(find_teacher(root),profile)
    done=failed=0
    start=time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(bench["selected_workers"]) as executor:
            while limit is None or done+failed<limit:
                amount=min(512,limit-done-failed) if limit is not None else 512
                rows=db.execute("""SELECT p.id,p.fen,coalesce(l.attempts,0),p.ordinal FROM pool.positions p
                    LEFT JOIN labels l ON l.id=p.id AND l.profile=?
                    WHERE p.ordinal>? AND p.ordinal<=? AND l.cp IS NULL AND coalesce(l.attempts,0)<3
                    ORDER BY p.ordinal LIMIT ?""",(profile_id,cursor,size,amount)).fetchall()
                if not rows: break
                for result in executor.map(worker,[row[:3] for row in rows]):
                    db.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",(profile_id,*result))
                    done+=int(result[1] is not None); failed+=int(result[1] is None)
                db.commit()
                cursor=rows[-1][3]
                metadata(db,cursor_key,cursor)
                elapsed=time.monotonic()-start
                if (done+failed)%4096==0:
                    rate=done/max(elapsed,.001)
                    remaining=max(0,size-cursor)
                    progress={"size":size,"cursor":cursor,"new_labels":done,"new_failures":failed,
                              "positions_per_second":rate,"eta_seconds":remaining/max(rate,.01),"seconds":elapsed}
                    save_json(root/cfg["reports"]/"label_progress.json",progress)
                    print(json.dumps(progress),flush=True)
    finally:
        worker.close(); db.commit()
    missing=db.execute("""SELECT count(*) FROM pool.positions p LEFT JOIN labels l
        ON l.id=p.id AND l.profile=? WHERE p.ordinal<=? AND l.cp IS NULL""",(profile_id,size)).fetchone()[0]
    report={"size":size,"new_labels":done,"new_failures":failed,"missing":missing,"seconds":time.monotonic()-start,
            "profile_id":profile_id,"profile":profile,"positions_per_second":done/max(time.monotonic()-start,.001)}
    save_json(root/cfg["reports"]/f"labels_{size}.json",report)
    with (root/cfg["reports"]/"label_history.jsonl").open("a") as stream: stream.write(json.dumps(report)+"\n")
    db.close()
    if missing and limit is None: raise RuntimeError(f"{missing} labels missing; retained progress can be resumed")
    return report
