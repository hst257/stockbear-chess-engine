from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from pathlib import Path

import chess
import chess.engine

from .common import connect, digest, file_hash, metadata, save_json


def find_teacher(root: Path) -> Path:
    candidates = list(root.glob("stockfish/**/*.exe")) + list(root.glob("stockfish-*/**/stockfish*.exe"))
    if len(candidates) != 1:
        raise ValueError(f"Expected one Stockfish executable; found {candidates}")
    return candidates[0]


def teacher_profile(root: Path, cfg: dict) -> dict:
    exe = find_teacher(root)
    return {"executable": str(exe.relative_to(root)), "sha256": file_hash(exe),
            "nodes": cfg["teacher"]["nodes"], "threads": 1, "hash_mb": cfg["teacher"]["hash_mb"],
            "clear_hash_each_position": True, "mate_cp": 2000, "score_pov": "side_to_move",
            "counters": "0 1", "version": 2}


class Worker:
    def __init__(self, exe: Path, profile: dict):
        self.exe = exe
        self.profile = profile
        self.local = threading.local()
        self.engines = []
        self.lock = threading.Lock()

    def engine(self):
        if getattr(self.local, "engine", None) is None:
            engine = chess.engine.SimpleEngine.popen_uci(str(self.exe), timeout=30)
            options = {"Threads": 1, "Hash": self.profile["hash_mb"]}
            if "SyzygyPath" in engine.options:
                options["SyzygyPath"] = ""
            if "UCI_LimitStrength" in engine.options:
                options["UCI_LimitStrength"] = False
            engine.configure(options)
            self.local.engine = engine
            with self.lock:
                self.engines.append(engine)
        return self.local.engine

    def __call__(self, row):
        pid, fen, previous_attempts = row
        error = None
        for attempt in range(previous_attempts, 3):
            try:
                engine = self.engine()
                engine.configure({"Clear Hash": None})
                board = chess.Board(fen)
                info = engine.analyse(board, chess.engine.Limit(nodes=self.profile["nodes"]), game=object())
                score = info["score"].pov(board.turn)
                raw_cp = score.score(mate_score=32000)
                cp = (2000 if raw_cp > 0 else -2000) if score.is_mate() else raw_cp
                return (pid, cp, score.mate(), info.get("depth"),
                        info.get("nodes"), attempt + 1, None)
            except (chess.engine.EngineError, TimeoutError, OSError) as exc:
                error = f"{type(exc).__name__}: {exc}"[:1000]
                engine = getattr(self.local, "engine", None)
                if engine:
                    try:
                        engine.close()
                    except Exception:
                        pass
                self.local.engine = None
        return (pid, None, None, None, None, 3, error)

    def close(self):
        for engine in self.engines:
            try:
                engine.quit()
            except (chess.engine.EngineError, TimeoutError, OSError):
                engine.close()


def label(root: Path, cfg: dict, limit: int | None = None) -> dict:
    start = time.monotonic()
    db = connect(root / cfg["cache"])
    db.execute("""CREATE TABLE IF NOT EXISTS labels (
        profile TEXT NOT NULL, id TEXT NOT NULL, cp INTEGER, mate INTEGER,
        depth INTEGER, nodes INTEGER, attempts INTEGER NOT NULL, error TEXT,
        PRIMARY KEY(profile,id))""")
    profile = teacher_profile(root, cfg)
    profile_id = digest(json.dumps(profile, sort_keys=True))
    metadata(db, f"profile:{profile_id}", profile)
    db.execute("ATTACH DATABASE ? AS corpus", (str(root / cfg["dataset"]),))
    query = """SELECT p.id,p.fen,coalesce(l.attempts,0) FROM corpus.positions p
               LEFT JOIN labels l ON l.profile=? AND l.id=p.id
               WHERE l.cp IS NULL AND coalesce(l.attempts,0)<3 ORDER BY p.id LIMIT ?"""
    worker = Worker(find_teacher(root), profile)
    done = 0
    failed = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg["teacher"]["workers"]) as pool:
            while limit is None or done + failed < limit:
                batch_size = min(128, limit - done - failed) if limit is not None else 128
                rows = db.execute(query, (profile_id, batch_size)).fetchall()
                if not rows:
                    break
                for pid, cp, mate, depth, nodes, attempts, error in pool.map(worker, rows):
                    db.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",
                               (profile_id, pid, cp, mate, depth, nodes, attempts, error))
                    done += int(cp is not None)
                    failed += int(cp is None)
                db.commit()
                if (done + failed) % 1024 == 0:
                    print(f"Teacher: {done} new labels, {failed} failures, {done/max(time.monotonic()-start,1):.1f} positions/s", flush=True)
    finally:
        db.commit()
        worker.close()
    total, remaining = db.execute("""SELECT count(*),sum(l.cp IS NULL) FROM corpus.positions p
        LEFT JOIN labels l ON l.profile=? AND l.id=p.id""", (profile_id,)).fetchone()
    stats = db.execute("""SELECT min(depth),avg(depth),max(depth),avg(nodes),sum(mate IS NOT NULL)
        FROM labels JOIN corpus.positions USING(id) WHERE profile=? AND cp IS NOT NULL""", (profile_id,)).fetchone()
    report = {"profile_id": profile_id, "profile": profile, "total": total, "remaining": remaining or 0,
              "new_labels": done, "new_failures": failed, "seconds": time.monotonic()-start,
              "positions_per_second": done / max(time.monotonic()-start, 0.001),
              "depth_min_mean_max": stats[:3], "mean_nodes": stats[3], "mate_labels": stats[4]}
    save_json(root / cfg["run"] / "teacher_report.json", report)
    with (root / cfg["run"] / "label_history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps(report, sort_keys=True) + "\n")
    db.close()
    print(json.dumps(report), flush=True)
    return report
