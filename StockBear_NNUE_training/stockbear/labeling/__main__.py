"""Run manually: python -m stockbear.labeling --help (no training imports)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sys

import chess
import numpy
import zstandard

from ..common import digest, file_hash
from ..teacher import find_teacher
from .ingest import finalize, ingest, inventory
from .output import export, prepare, validate
from .storage import (VERSION, attach_existing, atomic_json, connect, counts, get_meta,
                      corpus_snapshot, initialize, record_error, set_meta, source_hashes, utc, writer_lock)
from .teacher import identify, label

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "data/labeling/gm-extra-v1"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("run","status","validate","export","prepare"))
    result.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    result.add_argument("--input", type=Path)
    result.add_argument("--stockfish", type=Path)
    result.add_argument("--existing-corpus", type=Path, action="append")
    for name in ("nodes","threads","workers","hash-mb","seed","positions-per-game","min-ply",
                 "max-ply","ply-gap","prefix-plies","max-attempts","limit"):
        result.add_argument("--"+name, type=int)
    result.add_argument("--timeout", type=float)
    result.add_argument("--progress-seconds", type=float)
    result.add_argument("--encoding")
    result.add_argument("--resume", action="store_true")
    result.add_argument("--dry-run", action="store_true", default=None,
                        help="Entire pipeline, bounded queue of at most 100 positions. Use a separate output.")
    result.add_argument("--retry-failed", action="store_true")
    result.add_argument("--allow-partial", action="store_true",
                        help="Explicitly mark incomplete validation/export; never declare it complete.")
    result.add_argument("--destination", type=Path)
    result.add_argument("--features", choices=("v2","v3-full","v3-bucket16"), default="v2")
    return result


def configuration(args: argparse.Namespace, saved: dict | None) -> dict:
    cfg = dict(saved) if saved else {
        "input":str((ROOT/"data/raw/new_data").resolve()),"nodes":16384,"threads":1,"workers":2,
        "hash_mb":64,"seed":20261015,"positions_per_game":16,"min_ply":16,"max_ply":240,
        "ply_gap":4,"prefix_plies":20,"max_attempts":3,"timeout":30.,"progress_seconds":10.,
        "encoding":"utf-8-sig","limit":None,"dry_run":False,
        "existing_corpus":[str((ROOT/p).resolve()) for p in ("data/processed/full.sqlite","data/v2/pool.sqlite")]}
    for key in list(cfg)+["stockfish"]:
        value = getattr(args,key,None)
        if value is not None:
            if key=="existing_corpus":
                value = [str(p.resolve()) for p in value]
            elif key in ("input","stockfish"):
                value = str(value.resolve())
            cfg[key] = value
    if "stockfish" not in cfg:
        cfg["stockfish"] = str(find_teacher(ROOT).resolve())
    if cfg["dry_run"]:
        cfg["limit"] = cfg["limit"] if cfg["limit"] is not None else 100
        if not 1<=cfg["limit"]<=100:
            raise ValueError("--dry-run is limited to at most 100 positions")
    if saved and cfg!=saved:
        raise ValueError("Configuration changed on resume; omit overrides or use a fresh output directory")
    positive = ("nodes","threads","workers","hash_mb","positions_per_game","min_ply","max_ply",
                "ply_gap","prefix_plies","max_attempts","timeout","progress_seconds")
    if any(cfg[k]<=0 for k in positive) or (cfg["limit"] is not None and cfg["limit"]<1):
        raise ValueError("Budgets, sampling intervals and limits must be positive")
    if cfg["min_ply"]>cfg["max_ply"]:
        raise ValueError("min-ply exceeds max-ply")
    budget = max(1,(os.cpu_count() or 2)//2)
    if cfg["workers"]*cfg["threads"]>budget or cfg["workers"]>8:
        raise ValueError(f"Concurrency exceeds conservative laptop cap ({budget} CPU threads, at most 8 workers)")
    if cfg["hash_mb"]>4096 or cfg["workers"]*cfg["hash_mb"]>4096:
        raise ValueError("Total teacher hash allocation is capped at 4096 MiB")
    if not Path(cfg["input"]).is_dir() or not Path(cfg["stockfish"]).is_file():
        raise ValueError("Input directory or Stockfish executable is missing")
    for path in cfg["existing_corpus"]:
        if not Path(path).is_file():
            raise ValueError(f"Existing corpus missing (deduplication will not be silently disabled): {path}")
    return cfg


def output_guard(path: Path, cfg: dict | None = None) -> None:
    system_drive = os.environ.get("SystemDrive","C:").casefold()
    if os.name=="nt" and path.drive.casefold()==system_drive:
        raise ValueError("Use a non-system project drive for labeling outputs")
    protected = [ROOT/"data/raw",ROOT/"data/v2",ROOT/"data/v3",ROOT/"data/processed",ROOT/"data/cache",
                 ROOT/"runs",ROOT/"exports",ROOT/"reports",ROOT.parent/"engine"]
    if cfg:
        protected += [Path(cfg["input"]),*(Path(p) for p in cfg["existing_corpus"]),Path(cfg["stockfish"])]
    for item in protected:
        item = item.resolve()
        if path==item or path in item.parents or item in path.parents:
            raise ValueError(f"Output would overlap preserved input/research: {item}")


def check_signature(saved: dict, cfg: dict) -> None:
    if saved["version"]!=VERSION or saved["code"]!=source_hashes():
        raise ValueError("Pipeline source/version changed; preserve this run and use the matching revision or a fresh output")
    if saved["sources"]!=inventory(Path(cfg["input"])):
        raise ValueError("Input files changed; use a fresh output directory")
    for old in saved["existing_corpora"]:
        if corpus_snapshot(Path(old["path"]))!=old:
            raise ValueError(f"Frozen corpus changed: {old['path']}")
    if file_hash(Path(cfg["stockfish"]))!=saved["teacher_sha256"]:
        raise ValueError("Stockfish executable changed")
    if saved["runtime"]!=runtime():
        raise ValueError("Python/dependency versions changed; use the saved runtime for exact resume")


def runtime() -> dict:
    return {"python":platform.python_version(),"chess":chess.__version__,
            "numpy":numpy.__version__,"zstandard":zstandard.__version__}


def execute(args: argparse.Namespace) -> None:
    directory = args.output.resolve()
    database = directory/"pipeline.sqlite"
    if args.action=="status":
        with connect(database,readonly=True) as db:
            print(json.dumps({"stage":get_meta(db,"stage"),**counts(db),
                "sources":[dict(r) for r in db.execute("SELECT path,cursor,complete FROM sources")],
                "last_progress":get_meta(db,"last_progress"),
                "recent_errors":[dict(r) for r in db.execute("SELECT * FROM errors ORDER BY sequence DESC LIMIT 5")]},indent=2))
        return
    output_guard(directory)
    existed = database.exists()
    if args.action=="run" and existed and not args.resume:
        raise ValueError("Output already exists; use --resume or choose a fresh directory")
    if not existed and (args.resume or args.action!="run"):
        raise ValueError("No saved pipeline database exists at this output")
    if not existed and directory.exists() and any(directory.iterdir()):
        raise ValueError("Fresh output must be empty; existing files will not be overwritten")
    with writer_lock(directory), connect(database) as db:
        initialize(db)
        saved = get_meta(db,"config")
        cfg = configuration(args,saved)
        output_guard(directory,cfg)
        if saved:
            check_signature(get_meta(db,"signature"),cfg)
        else:
            print("Fingerprinting input/corpus files and identifying the local teacher...",flush=True)
            sources = inventory(Path(cfg["input"]))
            profile,teacher = identify(cfg,ROOT)
            signature = {"version":VERSION,"config":cfg,"sources":sources,"code":source_hashes(),
                "existing_corpora":[corpus_snapshot(Path(p)) for p in cfg["existing_corpus"]],
                "teacher_sha256":profile["sha256"],"runtime":runtime()}
            with db:
                set_meta(db,"config",cfg);set_meta(db,"signature",signature)
                set_meta(db,"profile",profile);set_meta(db,"profile_id",digest(json.dumps(profile,sort_keys=True)))
                set_meta(db,"teacher",teacher);set_meta(db,"created_utc",utc())
                db.executemany("INSERT INTO sources(id,path,sha256,bytes) VALUES (?,?,?,?)",
                    [(s["id"],s["path"]+("::"+s["member"] if s["member"] else ""),s["sha256"],s["bytes"]) for s in sources])
            atomic_json(directory/"config.json",cfg)
        aliases = attach_existing(db,cfg["existing_corpus"])
        try:
            if args.action=="run":
                with db: set_meta(db,"stage","ingesting")
                ingest(db,cfg,get_meta(db,"signature")["sources"])
                with db: set_meta(db,"stage","planning")
                finalize(db,cfg,aliases)
                with db: set_meta(db,"stage","labeling")
                label(db,cfg,directory,args.retry_failed)
            # A multi-hour run must also verify identities at completion, not only startup.
            check_signature(get_meta(db,"signature"),cfg)
            report = validate(db,directory,aliases,args.allow_partial)
            if args.action in ("run","export"):
                dest = (args.destination or directory/"export").resolve()
                output_guard(dest,cfg)
                if directory==dest or dest in directory.parents:
                    raise ValueError("Export destination cannot replace the live database directory")
                export(db,report,dest)
            elif args.action=="prepare":
                dest = (args.destination or directory/"prepared"/args.features).resolve()
                output_guard(dest,cfg)
                if directory==dest or dest in directory.parents:
                    raise ValueError("Prepared output cannot replace the live database directory")
                prepare(db,report,dest,args.features)
            with db: set_meta(db,"stage","complete" if report["complete"] else "partial")
            print(json.dumps({"output":str(directory),"action":args.action,"validation":report},indent=2),flush=True)
        except BaseException as exc:
            with db:
                record_error(db,"pipeline","",args.action,f"{type(exc).__name__}: {exc}")
            raise


def main() -> int:
    try:
        execute(parser().parse_args())
        return 0
    except KeyboardInterrupt:
        print("Interrupted safely. Resume with the same output and --resume.",file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}",file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
