"""Durable storage, exclusive writers and read-only original corpus access."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterator

from ..common import digest, file_hash

VERSION = 1
SPLITS = ("train", "validation", "test")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    publish(temporary,path)


def publish(temporary: Path, path: Path) -> None:
    # Antivirus/readers can hold a Windows file briefly. Preserve the old complete file.
    for attempt in range(20):
        try:
            os.replace(temporary,path)
            return
        except PermissionError:
            if attempt==19:
                raise
            time.sleep(.1)


@contextmanager
def writer_lock(directory: Path) -> Iterator[None]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".writer.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        for attempt in range(10):
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if attempt==9:
                    raise RuntimeError("Another process owns this output directory") from exc
                # TerminateProcess can signal before Windows finishes releasing byte locks.
                time.sleep(.05)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + ("?mode=ro" if readonly else "?mode=rwc")
    db = sqlite3.connect(uri, uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA temp_store=MEMORY")
    if readonly:
        db.execute("PRAGMA query_only=ON")
    else:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
    return db


def initialize(db: sqlite3.Connection) -> None:
    identity = db.execute("PRAGMA application_id").fetchone()[0]
    populated = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    if identity != 0x53424C31 and (identity or populated):
        raise ValueError("Existing database is not owned by this labeling pipeline")
    db.execute("PRAGMA application_id=1396853809")  # 0x53424c31 = SBL1.
    db.executescript("""
      CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,path TEXT NOT NULL,sha256 TEXT NOT NULL,
        bytes INTEGER NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,complete INTEGER NOT NULL DEFAULT 0);
      CREATE TABLE IF NOT EXISTS games(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
        number INTEGER NOT NULL,legacy_gid TEXT NOT NULL,headers TEXT NOT NULL,moves_hash TEXT NOT NULL,
        group_id TEXT,split TEXT,UNIQUE(source_id,number));
      CREATE TABLE IF NOT EXISTS game_keys(game TEXT NOT NULL REFERENCES games(id),key TEXT NOT NULL,
        PRIMARY KEY(game,key));
      CREATE INDEX IF NOT EXISTS key_idx ON game_keys(key);
      CREATE TABLE IF NOT EXISTS observations(id TEXT NOT NULL,game TEXT NOT NULL REFERENCES games(id),
        fen TEXT NOT NULL,ply INTEGER NOT NULL,outcome REAL NOT NULL,phase TEXT NOT NULL,
        category TEXT NOT NULL,flags TEXT NOT NULL,year INTEGER NOT NULL,priority TEXT NOT NULL,
        PRIMARY KEY(game,id));
      CREATE INDEX IF NOT EXISTS observation_id ON observations(id);
      CREATE TABLE IF NOT EXISTS prior_keys(key TEXT NOT NULL,split TEXT NOT NULL,gid TEXT NOT NULL,
        PRIMARY KEY(key,split,gid));
      CREATE TABLE IF NOT EXISTS existing_hits(id TEXT NOT NULL,gid TEXT NOT NULL,split TEXT NOT NULL,
        PRIMARY KEY(id,gid,split));
      CREATE TABLE IF NOT EXISTS groups(id TEXT PRIMARY KEY,split TEXT,quarantine TEXT,anchors TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,fen TEXT NOT NULL,game_id TEXT NOT NULL,
        split TEXT NOT NULL CHECK(split IN ('train','validation','test')),
        source TEXT NOT NULL,ply INTEGER NOT NULL,outcome REAL NOT NULL,
        phase TEXT NOT NULL,category TEXT NOT NULL,flags TEXT NOT NULL,priority TEXT NOT NULL,
        ordinal INTEGER NOT NULL UNIQUE,owner TEXT NOT NULL REFERENCES games(id),year INTEGER NOT NULL);
      CREATE INDEX IF NOT EXISTS position_split ON positions(split,ordinal);
      CREATE TABLE IF NOT EXISTS labels(profile TEXT NOT NULL,id TEXT NOT NULL REFERENCES positions(id),
        cp INTEGER,mate INTEGER,depth INTEGER,nodes INTEGER,attempts INTEGER NOT NULL DEFAULT 0,
        error TEXT,failed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(profile,id));
      CREATE TABLE IF NOT EXISTS errors(sequence INTEGER PRIMARY KEY,utc TEXT NOT NULL,stage TEXT NOT NULL,
        source TEXT,record TEXT,message TEXT NOT NULL);
    """)
    db.commit()


def get_meta(db: sqlite3.Connection, key: str) -> Any:
    row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def set_meta(db: sqlite3.Connection, key: str, value: Any) -> None:
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (key, json.dumps(value, sort_keys=True)))


def record_error(db: sqlite3.Connection, stage: str, source: str, record: str, error: Any) -> None:
    db.execute("INSERT INTO errors(utc,stage,source,record,message) VALUES (?,?,?,?,?)",
               (utc(), stage, source, record, str(error)[:4000]))


def attach_existing(db: sqlite3.Connection, paths: list[str]) -> list[str]:
    aliases = []
    for index, value in enumerate(paths):
        alias = f"old{index}"
        db.execute(f"ATTACH DATABASE ? AS {alias}", (Path(value).resolve().as_uri() + "?mode=ro",))
        columns = {r[1] for r in db.execute(f"PRAGMA {alias}.table_info(positions)")}
        if not {"id", "fen", "game_id", "split"} <= columns:
            raise ValueError(f"Not a StockBear position corpus: {value}")
        aliases.append(alias)
    return aliases


def source_hashes() -> dict[str, str]:
    paths = list(Path(__file__).parent.glob("*.py"))
    parent = Path(__file__).parents[1]
    paths += [parent / "common.py", parent / "sample.py", parent / "features.py",
              parent / "v2/data.py", parent / "v3/features.py"]
    return {p.relative_to(parent).as_posix(): digest(p.read_text(encoding="utf-8")) for p in sorted(paths)}


def corpus_snapshot(path: Path) -> dict:
    wal = Path(str(path)+"-wal")
    return {"path":str(path.resolve()),"sha256":file_hash(path),
            "wal_sha256":file_hash(wal) if wal.exists() and wal.stat().st_size else None}


def counts(db: sqlite3.Connection) -> dict:
    total = db.execute("SELECT count(*) FROM positions").fetchone()[0]
    done, failed, attempts = db.execute("SELECT coalesce(sum(cp IS NOT NULL),0),"
        "coalesce(sum(failed),0),coalesce(sum(attempts),0) FROM labels").fetchone()
    return {"positions": total, "completed": done, "failed": failed,
            "pending": total - done - failed, "remaining": total - done, "attempts": attempts,
            "sources_complete": db.execute("SELECT count(*) FROM sources WHERE complete=1").fetchone()[0],
            "sources_total": db.execute("SELECT count(*) FROM sources").fetchone()[0],
            "games": db.execute("SELECT count(*) FROM games").fetchone()[0],
            "errors": db.execute("SELECT count(*) FROM errors").fetchone()[0]}
