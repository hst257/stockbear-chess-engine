from __future__ import annotations

import heapq
import io
import json
import random
import time
from contextlib import contextmanager
from pathlib import Path

import chess
import chess.pgn
import zstandard

from .common import connect, digest, file_hash, metadata, save_json


def game_id(headers: dict) -> str:
    # Result, clock annotations and move count change in live broadcast snapshots.
    # Keep these out of the identity. Missing-header games conservatively group together.
    fields = ("Event", "Date", "Round", "White", "Black")
    return digest(json.dumps([str(headers.get(k, "?")).strip().casefold() for k in fields]))


def split_for(gid: str, seed: int) -> str:
    value = int(digest(f"split:{seed}:{gid}")[:16], 16) % 10000
    return "train" if value < 8000 else "validation" if value < 9000 else "test"


def canonical_fen(board: chess.Board) -> str:
    # This is a static evaluator: normalize draw/fullmove counters, preserve legal EP.
    return " ".join(board.fen(en_passant="legal").split()[:4]) + " 0 1"


@contextmanager
def pgn_stream(path: Path):
    with path.open("rb") as raw:
        with zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as decompressed:
            with io.TextIOWrapper(decompressed, encoding="utf-8-sig", errors="replace") as text:
                yield text


class SelectedGameBuilder(chess.pgn.GameBuilder):
    def __init__(self, selected: set[str]):
        super().__init__()
        self.selected = selected

    def end_headers(self):
        if game_id(self.game.headers) not in self.selected:
            return chess.pgn.SKIP
        return None

    def begin_variation(self):
        return chess.pgn.SKIP

    def visit_comment(self, comment):
        pass

    def handle_error(self, error):
        self.game.errors.append(error)


def choose_games(path: Path, limit: int, seed: int) -> tuple[set[str], dict]:
    heap: list[tuple[int, str]] = []
    selected: set[str] = set()
    count = 0
    with pgn_stream(path) as stream:
        while (headers := chess.pgn.read_headers(stream)) is not None:
            count += 1
            gid = game_id(headers)
            if gid in selected:
                continue
            rank = int(digest(f"sample:{seed}:{gid}"), 16)
            item = (-rank, gid)
            if len(heap) < limit:
                heapq.heappush(heap, item)
                selected.add(gid)
            elif rank < -heap[0][0]:
                removed = heapq.heapreplace(heap, item)
                selected.remove(removed[1])
                selected.add(gid)
    return selected, {"games_seen": count, "selected_games": len(selected)}


def positions_from_game(game: chess.pgn.Game, cfg: dict) -> list[tuple[str, int, float]]:
    gid = game_id(game.headers)
    rng = random.Random(f"positions:{cfg['seed']}:{gid}")
    result = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}.get(game.headers.get("Result"))
    if result is None or game.errors or game.headers.get("Variant", "Standard") not in ("Standard", "Chess"):
        return []
    board = game.board()
    if board.chess960 or not board.is_valid():
        return []
    reservoir = []
    eligible = 0
    last_eligible_ply = -100
    for ply, move in enumerate(game.mainline_moves(), 1):
        noisy = board.is_capture(move) or move.promotion is not None
        board.push(move)
        if ply < cfg["min_ply"] or ply > cfg["max_ply"]:
            continue
        if noisy or board.is_check() or board.is_game_over(claim_draw=False):
            continue
        if ply - last_eligible_ply < cfg["ply_gap"]:
            continue
        last_eligible_ply = ply
        eligible += 1
        row = (canonical_fen(board), ply, result if board.turn else 1.0 - result)
        if len(reservoir) < cfg["positions_per_game"]:
            reservoir.append(row)
        else:
            index = rng.randrange(eligible)
            if index < len(reservoir):
                reservoir[index] = row
    return sorted(reservoir, key=lambda x: x[1])


def sample(root: Path, cfg: dict) -> dict:
    start = time.monotonic()
    db = connect(root / cfg["dataset"])
    db.executescript("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY, fen TEXT NOT NULL, game_id TEXT NOT NULL,
            split TEXT NOT NULL CHECK(split IN ('train','validation','test')),
            source TEXT NOT NULL, ply INTEGER NOT NULL, outcome REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS split_idx ON positions(split);
    """)
    files = sorted((root / "data/raw").glob("*.pgn.zst"))
    if len(files) != len(cfg["months"]) or {p.name.split("_")[-1].split(".")[0] for p in files} != set(cfg["months"]):
        raise ValueError("Expected exactly the configured monthly PGN.zst files in data/raw")
    source_manifest = [{"name": p.name, "bytes": p.stat().st_size, "sha256": file_hash(p)} for p in files]
    signature = {"sampler": cfg["sampler"], "seed": cfg["seed"], "sources": source_manifest, "version": 1}
    previous = metadata(db, "sampling_signature")
    if previous is not None and previous != signature:
        raise ValueError("Dataset configuration/source changed; use a new dataset path")
    metadata(db, "sampling_signature", signature)
    completed = metadata(db, "completed_sources") or []
    reports = metadata(db, "source_reports") or {}
    for path in files:
        if path.name in completed:
            continue
        print(f"Selecting games throughout {path.name}", flush=True)
        selected, report = choose_games(path, cfg["sampler"]["games_per_month"], cfg["seed"])
        encountered = set()
        invalid = 0
        attempted = 0
        with pgn_stream(path) as stream:
            while (game := chess.pgn.read_game(stream, Visitor=lambda: SelectedGameBuilder(selected))) is not None:
                gid = game_id(game.headers)
                if gid not in selected or gid in encountered:
                    continue
                encountered.add(gid)
                rows = positions_from_game(game, {**cfg["sampler"], "seed": cfg["seed"]})
                invalid += int(not rows)
                for fen, ply, outcome in rows:
                    attempted += 1
                    db.execute("INSERT OR IGNORE INTO positions VALUES (?,?,?,?,?,?,?)", (
                        digest(fen), fen, gid, split_for(gid, cfg["seed"]), path.name, ply, outcome))
                if len(encountered) % 100 == 0:
                    db.commit()
        db.commit()
        report.update(games_without_positions=invalid, attempted_positions=attempted)
        reports[path.name] = report
        completed.append(path.name)
        metadata(db, "source_reports", reports)
        metadata(db, "completed_sources", completed)
        print(f"Sampled {path.name}: {report}", flush=True)
    counts = dict(db.execute("SELECT split,count(*) FROM positions GROUP BY split"))
    overlap = db.execute("SELECT count(*) FROM (SELECT game_id FROM positions GROUP BY game_id HAVING count(DISTINCT split)>1)").fetchone()[0]
    assert overlap == 0
    report = {"positions": counts, "source_reports": reports, "game_split_overlap": overlap,
              "unique_positions": sum(counts.values()), "seconds": time.monotonic() - start,
              "sources": source_manifest, "game_count": db.execute("SELECT count(DISTINCT game_id) FROM positions").fetchone()[0]}
    metadata(db, "sample_report", report)
    save_json(root / cfg["run"] / "sample_report.json", report)
    db.close()
    return report
