from __future__ import annotations

import json
from pathlib import Path

import chess

from .common import connect, digest, save_json
from .features import MAX_ACTIVE, active_features
from .sample import canonical_fen
from .teacher import Worker, find_teacher, teacher_profile


def validate(root: Path, cfg: dict, repeat_teacher: int = 16) -> dict:
    db = connect(root / cfg["dataset"])
    profile = teacher_profile(root, cfg)
    profile_id = digest(json.dumps(profile, sort_keys=True))
    db.execute("ATTACH DATABASE ? AS cache", (str(root / cfg["cache"]),))
    overlaps = db.execute("""SELECT count(*) FROM (SELECT game_id FROM positions
        GROUP BY game_id HAVING count(DISTINCT split)>1)""").fetchone()[0]
    fen_overlaps = db.execute("""SELECT count(*) FROM (SELECT fen FROM positions
        GROUP BY fen HAVING count(DISTINCT split)>1)""").fetchone()[0]
    missing = db.execute("""SELECT count(*) FROM positions p LEFT JOIN cache.labels l
        ON p.id=l.id AND l.profile=? WHERE l.cp IS NULL""", (profile_id,)).fetchone()[0]
    if overlaps or fen_overlaps or missing:
        raise AssertionError(f"Integrity failed: game overlap={overlaps}, FEN overlap={fen_overlaps}, missing={missing}")
    checked = 0
    for pid, fen in db.execute("SELECT id,fen FROM positions ORDER BY id"):
        board = chess.Board(fen)
        if digest(fen) != pid or canonical_fen(board) != fen or not board.is_valid():
            raise AssertionError(f"Invalid canonical position: {pid}")
        if any(len(active_features(board, color)) > MAX_ACTIVE for color in chess.COLORS):
            raise AssertionError("Feature capacity exceeded")
        checked += 1
    rows = db.execute("""SELECT p.id,p.fen,l.cp,l.mate,l.depth,l.nodes FROM positions p
        JOIN cache.labels l ON p.id=l.id WHERE l.profile=? ORDER BY p.id LIMIT ?""",
        (profile_id, repeat_teacher)).fetchall()
    worker = Worker(find_teacher(root), profile)
    repeated = []
    try:
        for pid, fen, cp, mate, depth, nodes in rows:
            result = worker((pid, fen, 0))
            if result[1:5] != (cp, mate, depth, nodes):
                raise AssertionError(f"Teacher repeat mismatch for {pid}: cached={(cp,mate,depth,nodes)}, repeated={result[1:5]}")
            repeated.append(pid)
    finally:
        worker.close()
    report = {"canonical_positions_checked": checked, "game_overlap": overlaps,
              "exact_fen_overlap": fen_overlaps, "missing_labels": missing,
              "teacher_repeat_positions": len(repeated), "teacher_repeats_exact_cp_mate_depth_nodes": True,
              "teacher_profile_id": profile_id,
              "splits": {split: {"positions": count, "games": games} for split, count, games in
                         db.execute("SELECT split,count(*),count(DISTINCT game_id) FROM positions GROUP BY split")}}
    save_json(root / cfg["run"] / "validation_report.json", report)
    db.close()
    return report
