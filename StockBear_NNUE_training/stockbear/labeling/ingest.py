"""Deterministic sampling, provenance and conservative game-family partitions."""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
import bz2
import gzip
import io
import json
import lzma
from pathlib import Path
import sqlite3
import time
import unicodedata
from typing import Iterator, TextIO
import zipfile

import chess
import chess.pgn
import zstandard

from ..common import digest, file_hash
from ..sample import canonical_fen, game_id, split_for
from ..v2.data import game_positions
from .storage import get_meta, record_error, set_meta

SUFFIXES = (".pgn", ".pgn.gz", ".pgn.bz2", ".pgn.xz", ".pgn.zst", ".zip")


def inventory(directory: Path) -> list[dict]:
    result = []
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        if not path.name.lower().endswith(SUFFIXES):
            continue
        members = [None]
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                members = sorted(x.filename for x in archive.infolist()
                                 if not x.is_dir() and x.filename.lower().endswith(".pgn"))
                if len(members) != len(set(members)):
                    raise ValueError(f"Duplicate ZIP member names: {path}")
        sha = file_hash(path)
        for member in members:
            relative = path.relative_to(directory).as_posix()
            result.append({"id": digest(relative + ":" + str(member)), "path": str(path.resolve()),
                "relative": relative, "member": member, "sha256": sha, "bytes": path.stat().st_size})
    if not result:
        raise ValueError(f"No supported PGN inputs in {directory}")
    return result


@contextmanager
def pgn_text(source: dict, encoding: str) -> Iterator[TextIO]:
    path = Path(source["path"])
    if source["member"] is not None:
        with zipfile.ZipFile(path) as archive, archive.open(source["member"]) as raw:
            with io.TextIOWrapper(raw, encoding=encoding, errors="strict") as stream:
                yield stream
    elif path.suffix.lower() == ".zst":
        with path.open("rb") as raw:
            with zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as reader:
                with io.TextIOWrapper(reader, encoding=encoding, errors="strict") as stream:
                    yield stream
    else:
        opener = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}.get(path.suffix.lower(), open)
        with opener(path, "rt", encoding=encoding, errors="strict") as stream:
            yield stream


class MainlineBuilder(chess.pgn.GameBuilder):
    def begin_variation(self):
        return chess.pgn.SKIP

    def visit_comment(self, comment: str) -> None:
        pass

    def handle_error(self, error: Exception) -> None:
        self.game.errors.append(error)


def normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value).casefold() if c.isalnum())


def extract(game: chess.pgn.Game, cfg: dict) -> tuple[list, str, set[str]]:
    if game.errors:
        raise ValueError("Malformed/illegal PGN: " + "; ".join(str(e) for e in game.errors))
    if game.headers.get("Result") not in ("1-0", "0-1", "1/2-1/2"):
        raise ValueError("Missing or unfinished game result")
    if game.headers.get("Variant", "Standard") not in ("Standard", "Chess"):
        raise ValueError("Unsupported variant")
    board = game.board()
    if board.chess960 or not board.is_valid():
        raise ValueError("Invalid initial orthodox position")
    initial = canonical_fen(board)
    moves = []
    for move in game.mainline_moves():
        if not board.is_legal(move):
            raise ValueError(f"Illegal move {move} at ply {len(moves)+1}")
        board.push(move)
        moves.append(move.uci())
        if not board.is_valid():
            raise ValueError("Invalid position after move")
    outcome = board.outcome(claim_draw=False)
    if outcome is not None and outcome.result() != game.headers["Result"]:
        raise ValueError("Terminal board contradicts PGN result")
    rows, moves_hash = game_positions(game, cfg)
    if not rows or moves_hash is None:
        raise ValueError("No eligible nonterminal sampled positions")
    # Repeated occurrences within a game count only once, using the earliest ply.
    unique = {}
    for row in sorted(rows, key=lambda r: r[2]):
        unique.setdefault(row[1], row)
    gid = game_id(game.headers)
    keys = {"header:" + gid, "moves:" + moves_hash}
    players = ":".join(sorted(normalized(game.headers.get(c, "")) for c in ("White", "Black")))
    if all(normalized(game.headers.get(c, "")) not in ("", "unknown") for c in ("White", "Black")):
        date = game.headers.get("Date", "")
        if len(date) == 10 and "?" not in date:
            keys.add("players-day:" + digest(players + date))
        prefix = cfg["prefix_plies"]
        if len(moves) >= prefix:
            keys.add("players-prefix:" + digest(players + initial + " ".join(moves[:prefix])))
    return list(unique.values()), moves_hash, keys


def ingest(db: sqlite3.Connection, cfg: dict, sources: list[dict]) -> None:
    tick = time.monotonic()
    for source in sources:
        state = db.execute("SELECT cursor,complete FROM sources WHERE id=?", (source["id"],)).fetchone()
        if state["complete"]:
            continue
        cursor, number = state["cursor"], 0
        print(f"Reading {source['relative']} (saved game {cursor})", flush=True)
        try:
            with pgn_text(source, cfg["encoding"]) as stream:
                while True:
                    game = chess.pgn.read_game(stream, Visitor=MainlineBuilder)
                    if game is None:
                        break
                    number += 1
                    if number <= cursor:
                        continue
                    with db:
                        try:
                            rows, moves_hash, keys = extract(game, cfg)
                            uid = digest(source["id"] + ":" + str(number))
                            headers = dict(game.headers)
                            year = headers.get("Date", "")[:4]
                            year = int(year) if year.isdigit() else 0
                            db.execute("INSERT INTO games(id,source_id,number,legacy_gid,headers,moves_hash) VALUES (?,?,?,?,?,?)",
                                (uid, source["id"], number, game_id(headers), json.dumps(headers, sort_keys=True), moves_hash))
                            db.executemany("INSERT INTO game_keys VALUES (?,?)", [(uid, key) for key in sorted(keys)])
                            db.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?)",
                                [(digest(fen), uid, fen, ply, outcome, phase, category, flags, year, priority)
                                 for priority,fen,ply,outcome,phase,category,flags in rows])
                        except (ValueError, KeyError, IndexError, chess.IllegalMoveError) as exc:
                            # Extraction finishes before inserts; storage errors are never treated as bad PGN.
                            record_error(db, "game", source["relative"], str(number), exc)
                        db.execute("UPDATE sources SET cursor=? WHERE id=?", (number, source["id"]))
                    if time.monotonic() - tick >= cfg["progress_seconds"]:
                        print(f"Ingested {number} games in current source; sampled observations "
                              f"{db.execute('SELECT count(*) FROM observations').fetchone()[0]:,}", flush=True)
                        tick = time.monotonic()
            if number < cursor:
                raise ValueError("Input ended before its saved cursor")
            # Recheck source bytes before accepting its final cursor.
            if file_hash(Path(source["path"])) != source["sha256"]:
                raise ValueError("Input changed during ingestion; use a fresh output")
            with db:
                db.execute("UPDATE sources SET complete=1 WHERE id=?", (source["id"],))
        except (OSError, EOFError, ValueError, zstandard.ZstdError, zipfile.BadZipFile) as exc:
            with db:
                record_error(db, "source", source["relative"], str(number), exc)
            raise RuntimeError(f"Source failed; progress retained: {source['path']}: {exc}") from exc


class Families:
    def __init__(self, ids: list[str]):
        self.parent = {gid: gid for gid in ids}

    def root(self, gid: str) -> str:
        while self.parent[gid] != gid:
            self.parent[gid] = self.parent[self.parent[gid]]
            gid = self.parent[gid]
        return gid

    def merge(self, a: str, b: str) -> None:
        a, b = self.root(a), self.root(b)
        if a != b:
            self.parent[max(a,b)] = min(a,b)


def finalize(db: sqlite3.Connection, cfg: dict, aliases: list[str]) -> None:
    if get_meta(db, "planned"):
        return
    print("Checking existing positions and game families before any labeling...", flush=True)
    # Entire planning step is one transaction. A crash cannot expose a half-planned queue.
    with db:
        for alias in aliases:
            db.execute(f"INSERT OR IGNORE INTO prior_keys SELECT 'header:'||game_id,split,game_id "
                       f"FROM {alias}.positions GROUP BY game_id,split")
            tables = {r[0] for r in db.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table'")}
            if "games" in tables:
                db.execute(f"INSERT OR IGNORE INTO prior_keys SELECT 'moves:'||g.moves,p.split,p.gid "
                           f"FROM {alias}.games g JOIN prior_keys p ON p.key='header:'||g.gid")
            db.execute(f"INSERT OR IGNORE INTO existing_hits SELECT DISTINCT o.id,p.game_id,p.split "
                       f"FROM (SELECT DISTINCT id FROM observations) o CROSS JOIN {alias}.positions p ON p.id=o.id")
        games = {r["id"]: dict(r) for r in db.execute("SELECT id,legacy_gid FROM games")}
        family = Families(list(games))
        owner = {}
        for game,key in db.execute("SELECT game,key FROM game_keys ORDER BY key,game"):
            if key in owner:
                family.merge(game, owner[key])
            else:
                owner[key] = game
        # Additional near-duplicate guard: three shared sampled late FENs.
        # Ignore ubiquitous boards for this graph (they are still position-deduplicated).
        shared = Counter()
        for row in db.execute("SELECT id,group_concat(game),count(*) n FROM observations WHERE ply>=24 "
                              "GROUP BY id HAVING n BETWEEN 2 AND 16"):
            ids = sorted(row[1].split(","))
            for i,a in enumerate(ids):
                for b in ids[i+1:]:
                    shared[a,b] += 1
        for (a,b), amount in shared.items():
            if amount >= 3:
                family.merge(a,b)
        anchors = defaultdict(set)
        for game,split,gid in db.execute("SELECT k.game,p.split,p.gid FROM game_keys k JOIN prior_keys p ON k.key=p.key"):
            anchors[family.root(game)].add((split,gid))
        for game,split,gid,n in db.execute("SELECT o.game,h.split,h.gid,count(*) n FROM observations o "
                "JOIN existing_hits h ON h.id=o.id WHERE o.ply>=24 GROUP BY o.game,h.split,h.gid HAVING n>=2"):
            anchors[family.root(game)].add((split,gid))
        components = defaultdict(list)
        for gid in games:
            components[family.root(gid)].append(gid)
        quarantined = 0
        for root,members in components.items():
            prior = anchors[root]
            prior_splits = {p[0] for p in prior}
            group = min((p[1] for p in prior), default=min(games[g]["legacy_gid"] for g in members))
            split = next(iter(prior_splits)) if len(prior_splits)==1 else split_for(group,cfg["seed"])
            reason = "conflicting frozen-corpus partitions" if len(prior_splits)>1 else None
            # Separate disconnected new components anchored to the same old game share one group.
            existing = db.execute("SELECT split,quarantine FROM groups WHERE id=?", (group,)).fetchone()
            if existing is not None and (existing["quarantine"] or existing["split"] != split):
                reason = "conflicting frozen-corpus partitions"
            db.execute("INSERT INTO groups VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "quarantine=coalesce(excluded.quarantine,groups.quarantine),split=excluded.split",
                       (group, split, reason, json.dumps(sorted(prior))))
            db.executemany("UPDATE games SET group_id=?,split=? WHERE id=?", [(group,split,g) for g in members])
        # Count quarantined groups, retain all observations and their exclusion reasons.
        quarantined = db.execute("SELECT count(*) FROM groups WHERE quarantine IS NOT NULL").fetchone()[0]
        candidates = db.execute("""SELECT o.*,g.group_id,g.split,s.path FROM observations o
            JOIN games g ON o.game=g.id JOIN groups f ON f.id=g.group_id JOIN sources s ON s.id=g.source_id
            WHERE f.quarantine IS NULL AND o.id NOT IN (SELECT id FROM existing_hits)
            AND o.id NOT IN (SELECT id FROM observations GROUP BY id HAVING min(outcome)!=max(outcome))
            ORDER BY o.id,o.priority,o.game"""
        )
        seen = set()
        selected = []
        for row in candidates:
            if row["id"] not in seen:
                seen.add(row["id"])
                selected.append(dict(row))
        # Global ID order makes --limit a deterministic bounded prefix, independent of workers.
        if cfg["limit"] is not None:
            selected = selected[:cfg["limit"]]
        db.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            (r["id"],r["fen"],r["group_id"],r["split"],r["path"],r["ply"],r["outcome"],r["phase"],
             r["category"],r["flags"],r["priority"],i,r["game"],r["year"])
            for i,r in enumerate(selected,1)])
        set_meta(db,"planned",True)
        set_meta(db,"sampling_report",{
            "observations":db.execute("SELECT count(*) FROM observations").fetchone()[0],
            "unique_sampled_positions":db.execute("SELECT count(DISTINCT id) FROM observations").fetchone()[0],
            "existing_positions_excluded":db.execute("SELECT count(DISTINCT id) FROM existing_hits").fetchone()[0],
            "conflicting_outcome_positions_excluded":db.execute("SELECT count(*) FROM (SELECT id FROM observations GROUP BY id HAVING min(outcome)!=max(outcome))").fetchone()[0],
            "families":db.execute("SELECT count(*) FROM groups").fetchone()[0],
            "quarantined_families":quarantined,"selected_positions":len(selected),
            "splits":dict(db.execute("SELECT split,count(*) FROM positions GROUP BY split")),
            "near_duplicate_policy":"Legacy header identity; complete move hash; normalized same-player/day or 20-ply prefix; >=3 uncommon shared sampled FENs after ply24. Frozen anchors by header/moves or >=2 late sampled matches to one old game. Conflicting anchors quarantine the family. Not a proof against arbitrary semantic similarity."})
    print(f"Queue ready: {len(selected):,} unique new positions; {quarantined} quarantined families", flush=True)
