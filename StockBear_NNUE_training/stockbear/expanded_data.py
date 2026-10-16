"""Build a new deduplicated corpus and v2/v3 arrays from existing labels only."""
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

import chess
import numpy as np

from .common import file_hash
from .features import encode, FEATURE_VERSION
from .sample import canonical_fen
from .v3.features import encode as encode_v3, from_v2
from .labeling import __main__ as labeling
from .labeling.ingest import Families
from .labeling.storage import atomic_json, connect, get_meta, publish, utc, writer_lock

ROOT = Path(__file__).resolve().parents[1]
SPLITS = ("train", "validation", "test")
FORMATS = ("v2", "v3-bucket16", "v3-full")
Y_COLUMNS = ("stm_cp", "stm_outcome", "stm_material", "ply", "phase_index",
             "tactical_heuristic", "year_or_0", "game_index")


def meta(db, key, value):
    db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)",(key,json.dumps(value,sort_keys=True)))


def attach(db, alias: str, path: Path):
    db.execute(f"ATTACH DATABASE ? AS {alias}",(path.resolve().as_uri()+"?mode=ro",))


def sources(root: Path, run: Path) -> dict[str, Path]:
    return {"v1":root/"data/processed/full.sqlite", "v2":root/"data/v2/pool.sqlite",
            "v1_labels":root/"data/cache/teacher.sqlite", "v2_labels":root/"data/v2/teacher.sqlite",
            "expanded":run/"pipeline.sqlite"}


def source_snapshot(paths: dict[str, Path]) -> dict:
    result = {}
    for name,path in paths.items():
        print(f"Fingerprinting preserved input: {name}",flush=True)
        wal=Path(str(path)+"-wal")
        result[name]={"path":str(path.resolve()),"bytes":path.stat().st_size,"sha256":file_hash(path),
                      "wal_sha256":file_hash(wal) if wal.exists() and wal.stat().st_size else None}
    return result


def validate_fen_batch(rows: list[tuple]) -> int:
    for pid,fen in rows:
        board=chess.Board(fen)
        if not board.is_valid() or board.chess960 or board.is_game_over() or canonical_fen(board)!=fen or hashlib.sha256(fen.encode()).hexdigest()!=pid:
            raise ValueError(f"Invalid/noncanonical source position: {pid}")
    return len(rows)


def readonly_audit(root: Path, run: Path, destination: Path, workers: int = 4) -> dict:
    validation_path=run/"validation.json"
    validation=json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else None
    with closing(connect(run/"pipeline.sqlite",readonly=True)) as db:
        db.execute("PRAGMA cache_size=-262144")
        cfg,signature=get_meta(db,"config"),get_meta(db,"signature")
        labeling.check_signature(signature,cfg)
        if not get_meta(db,"planned") or db.execute("SELECT 1 FROM sources WHERE complete=0 LIMIT 1").fetchone():
            raise ValueError("Source ingestion/planning is incomplete")
        quality=dict(db.execute("SELECT 'positions',count(*) FROM positions UNION ALL "
            "SELECT 'completed',count(*) FROM labels WHERE cp IS NOT NULL UNION ALL "
            "SELECT 'pending',count(*) FROM labels WHERE cp IS NULL UNION ALL "
            "SELECT 'failed',count(*) FROM labels WHERE failed!=0"))
        if quality["pending"] or quality["failed"] or quality["positions"]!=quality["completed"]:
            raise ValueError("New label counts are inconsistent/incomplete")
        report={"utc":utc(),"new_validation":validation,"quality":quality,
                "profile_id":get_meta(db,"profile_id"),"profile":get_meta(db,"profile"),
                "signature_unchanged":True,"errors_by_stage":dict(db.execute("SELECT stage,count(*) FROM errors GROUP BY stage")),
                "pipeline_events":[dict(r) for r in db.execute("SELECT utc,message FROM errors WHERE stage='pipeline'")],
                "skipped_game_reasons":[dict(r) for r in db.execute("SELECT message,count(*) AS records FROM errors WHERE stage='game' GROUP BY message ORDER BY records DESC")],
                "label_ranges":dict(db.execute("SELECT min(cp) AS cp_min,max(cp) AS cp_max,min(nodes) AS nodes_min,max(nodes) AS nodes_max,"
                    "min(depth) AS depth_min,max(depth) AS depth_max,sum(mate IS NOT NULL) AS mate_labels,sum(attempts) AS attempts FROM labels").fetchone()),
                "last_progress":get_meta(db,"last_progress")}
        if report["errors_by_stage"].get("teacher",0) or report["errors_by_stage"].get("source",0):
            raise ValueError("Inspect teacher/source errors before preparing training data")
        if any(not r["message"].startswith("KeyboardInterrupt") for r in report["pipeline_events"]):
            raise ValueError("Inspect unexpected pipeline failures before merging")
        checks={
          "database_integrity":"PRAGMA integrity_check",
          "foreign_keys":"PRAGMA foreign_key_check",
          "mixed_profiles":"SELECT 1 FROM labels WHERE profile!=? LIMIT 1",
          "family_split_leakage":"SELECT 1 FROM positions GROUP BY game_id HAVING count(DISTINCT split)>1 LIMIT 1",
          "quarantined_or_misassigned_families":"SELECT 1 FROM positions p JOIN groups g ON p.game_id=g.id WHERE g.quarantine IS NOT NULL OR p.split!=g.split LIMIT 1",
          "game_alias_split_leakage":"SELECT 1 FROM game_keys k JOIN games g ON k.game=g.id JOIN groups f ON g.group_id=f.id WHERE f.quarantine IS NULL GROUP BY k.key HAVING count(DISTINCT g.split)>1 LIMIT 1",
          "label_ranges_and_metadata":"SELECT 1 FROM labels WHERE typeof(cp)!='integer' OR abs(cp)>32000 OR typeof(depth)!='integer' OR depth<1 OR typeof(nodes)!='integer' OR nodes<1 OR error IS NOT NULL OR failed!=0 OR (mate IS NOT NULL AND (typeof(mate)!='integer' OR cp!=CASE WHEN mate>0 THEN 2000 ELSE -2000 END)) LIMIT 1",
          "result_perspective":"SELECT 1 FROM positions p CROSS JOIN games g ON g.id=p.owner WHERE json_extract(g.headers,'$.Result') IS NULL OR json_extract(g.headers,'$.Result') NOT IN ('1-0','0-1','1/2-1/2') OR p.outcome!=CASE WHEN substr(p.fen,instr(p.fen,' ')+1,1)='w' THEN CASE json_extract(g.headers,'$.Result') WHEN '1-0' THEN 1.0 WHEN '0-1' THEN 0.0 ELSE 0.5 END ELSE CASE json_extract(g.headers,'$.Result') WHEN '1-0' THEN 0.0 WHEN '0-1' THEN 1.0 ELSE 0.5 END END LIMIT 1"}
        report["checks"]={}
        for key,query in checks.items():
            print(f"Verifying complete source: {key}",flush=True)
            started=time.monotonic()
            rows=db.execute(query,(report["profile_id"],) if key=="mixed_profiles" else ()).fetchall()
            if (key=="database_integrity" and [tuple(r) for r in rows]!=[("ok",)]) or (key!="database_integrity" and rows):
                raise ValueError(f"Source validation failed: {key}")
            report["checks"][key]={"passed":True,"seconds":time.monotonic()-started}
        for alias,path in (("old_v1",root/"data/processed/full.sqlite"),("old_v2",root/"data/v2/pool.sqlite")):
            attach(db,alias,path)
            db.execute(f"PRAGMA {alias}.cache_size=-65536")
            print(f"Checking expanded-position disjointness against {alias}",flush=True)
            if db.execute(f"SELECT 1 FROM positions p CROSS JOIN {alias}.positions o ON o.id=p.id LIMIT 1").fetchone():
                raise ValueError("New corpus overlaps a frozen original position")
        cursor=db.execute("SELECT id,fen FROM positions ORDER BY ordinal")
        pending=deque();done=0;exhausted=False;started=last_tick=time.monotonic()
        with ProcessPoolExecutor(max_workers=workers) as pool:
            while pending or not exhausted:
                while not exhausted and len(pending)<workers*2:
                    batch=[tuple(r) for r in cursor.fetchmany(4096)]
                    if batch:pending.append(pool.submit(validate_fen_batch,batch))
                    else:exhausted=True
                if not pending:break
                done+=pending.popleft().result()
                if time.monotonic()-last_tick>=10:
                    rate=done/(time.monotonic()-started)
                    progress={"stage":"source-fen-verification","completed":done,"positions":quality["positions"],
                              "positions_per_second":rate,"eta_seconds":(quality["positions"]-done)/rate}
                    atomic_json(destination/"preparation-progress.json",progress)
                    print(f"Verified source FENs: {done:,}/{quality['positions']:,}; {rate:.0f}/s; ETA {(quality['positions']-done)/rate/60:.1f}m",flush=True)
                    last_tick=time.monotonic()
        if done!=quality["positions"]:raise ValueError("Source FEN validation count mismatch")
        report.update(all_fens_and_labels_checked=True,source_fens_checked=done,complete=True,
                      grouped_splits_disjoint=True,original_corpus_overlap=0,
                      finalization="Independent indexed read-only SQL and parallel board verification; original labels/checkpoints remain unchanged")
    export_path=run/"export/manifest.json"
    if export_path.exists():
        export_manifest=json.loads(export_path.read_text(encoding="utf-8"))
        if validation and export_manifest["validation"]["fingerprint"]!=validation["fingerprint"]:
            raise ValueError("New export/validation identity mismatch")
        for name,expected in export_manifest["files"].items():
            print(f"Checking completed export: {name}",flush=True)
            if file_hash(run/"export"/name)!=expected:raise ValueError(f"Corrupt completed export: {name}")
        report["export_files_verified"]=True
    else:
        report["export_files_verified"]=False
        report["export_note"]="Original JSONL export was not completed; this preparation verifies and reads the authoritative SQLite labels directly. No export is required for training."
    report["sources"]=source_snapshot(sources(root,run))
    for key,path in sources(root,run).items():
        if key=="expanded":continue  # Verified exhaustively above in this read-only audit.
        print(f"Checking original database integrity: {key}",flush=True)
        with closing(connect(path,readonly=True)) as db:
            db.execute("PRAGMA cache_size=-65536")
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError(f"Original database integrity failed: {path}")
    atomic_json(destination/"source-audit.json",report)
    return report


def group_mapping(db) -> tuple[list[tuple], dict]:
    """Unite stable IDs/full-mainline aliases/recorded anchors; never resplit a family."""
    partitions=defaultdict(set)
    for alias in ("v1","v2","expanded"):
        for gid,split in db.execute(f"SELECT game_id,split FROM {alias}.positions GROUP BY game_id,split"):
            partitions[gid].add(split)
    family=Families(list(partitions))

    def add(gid):
        family.parent.setdefault(gid,gid)

    previous={}
    for gid,moves in db.execute("SELECT gid,moves FROM v2.games ORDER BY moves,gid"):
        add(gid)
        if moves in previous:
            family.merge(gid,previous[moves])
        else:
            previous[moves]=gid
    for gid,anchors in db.execute("SELECT id,anchors FROM expanded.groups WHERE quarantine IS NULL"):
        add(gid)
        for split,anchor in json.loads(anchors):
            add(anchor)
            partitions[anchor].add(split)
            family.merge(gid,anchor)
    # Include every header/mainline anchor, even if a shared group's stored JSON
    # describes just its first component in the original frozen planner.
    for gid,anchor,split in db.execute("SELECT DISTINCT g.group_id,p.gid,p.split FROM expanded.game_keys k "
            "CROSS JOIN expanded.games g ON g.id=k.game CROSS JOIN expanded.prior_keys p ON p.key=k.key "
            "CROSS JOIN expanded.groups f ON f.id=g.group_id WHERE f.quarantine IS NULL"):
        add(gid);add(anchor)
        partitions[anchor].add(split)
        family.merge(gid,anchor)
    # Preserve the planner's two-shared-late-position links to old games as well.
    for gid,anchor,split in db.execute("SELECT g.group_id,h.gid,h.split FROM expanded.observations o "
            "JOIN expanded.existing_hits h ON h.id=o.id JOIN expanded.games g ON g.id=o.game "
            "JOIN expanded.groups f ON f.id=g.group_id WHERE o.ply>=24 AND f.quarantine IS NULL "
            "GROUP BY o.game,h.split,h.gid HAVING count(*)>=2"):
        add(gid);add(anchor)
        partitions[anchor].add(split)
        family.merge(gid,anchor)
    combined=defaultdict(set)
    for gid,splits in partitions.items():
        combined[family.root(gid)].update(splits)
    eligible=sorted(g for g,s in combined.items() if len(s)==1)
    numeric={gid:i for i,gid in enumerate(eligible)}
    if len(numeric)>=2**24:
        raise ValueError("Game index exceeds exact float32 integer capacity")
    rows=[]
    for gid in sorted(partitions):
        canonical=family.root(gid)
        splits=combined[canonical]
        split=next(iter(splits)) if len(splits)==1 else None
        rows.append((gid,canonical,split,numeric.get(canonical),int(split is None)))
    return rows,{"raw_game_ids":len(partitions),"canonical_families":len(combined),
                 "conflicting_split_families":sum(len(s)>1 for s in combined.values()),
                 "policy":"Stable game IDs, old complete-mainline aliases and all recorded new-to-old anchors are unioned. Conflicting frozen splits are quarantined; original partitions are never reassigned."}


def merge(root: Path, run: Path, destination: Path, audit: dict) -> dict:
    path=destination/"merged.sqlite"
    signature={"schema":1,"sources":audit["sources"],"profile_id":audit["profile_id"],
               "source_lf_sha256":hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n",b"\n")).hexdigest()}
    if path.exists():
        with closing(connect(path,readonly=True)) as db:
            if get_meta(db,"signature")!=signature:
                raise ValueError("Existing merge belongs to another source/code snapshot")
            report=get_meta(db,"report")
            if report:
                report["database_sha256"]=file_hash(path)
                saved=destination/"merge-report.json"
                if saved.exists() and json.loads(saved.read_text(encoding="utf-8"))!=report:
                    raise ValueError("Completed merged database/report changed")
                if not saved.exists():atomic_json(saved,report)
                return report
        raise ValueError("Incomplete merge retained; select a new empty output directory")
    print("Merging compatible labels into a new database; inputs remain read-only",flush=True)
    with closing(connect(path)) as db:
        db.execute("PRAGMA cache_size=-262144")
        for name,source in sources(root,run).items():
            attach(db,name,source)
            db.execute(f"PRAGMA {name}.cache_size=-65536")
        profile=audit["profile_id"]
        for alias in ("v1_labels","v2_labels"):
            teacher=get_meta_from_alias(db,alias,"profile:"+profile)
            if teacher!=audit["profile"]:
                raise ValueError(f"Teacher profile differs: {alias}")
        db.executescript("""
          CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE group_map(original_game TEXT PRIMARY KEY,game_id TEXT NOT NULL,split TEXT,
                                 game_index INTEGER,quarantine INTEGER NOT NULL);
          CREATE TABLE exclusions(id TEXT PRIMARY KEY,reason TEXT NOT NULL);
          CREATE TABLE duplicate_provenance(id TEXT PRIMARY KEY,v1_game TEXT,v2_game TEXT,v1_split TEXT,
              v2_split TEXT,v1_outcome REAL,v2_outcome REAL,cp_equal INTEGER);
          CREATE TABLE records(ordinal INTEGER PRIMARY KEY,id TEXT NOT NULL UNIQUE,fen TEXT NOT NULL,
              game_id TEXT NOT NULL,game_index INTEGER NOT NULL,split TEXT NOT NULL,origin TEXT NOT NULL,
              original_game TEXT NOT NULL,source TEXT NOT NULL,source_ordinal INTEGER,owner TEXT,
              ply INTEGER NOT NULL,outcome REAL NOT NULL,phase TEXT,category TEXT,flags TEXT,year INTEGER,
              cp INTEGER NOT NULL,mate INTEGER,depth INTEGER NOT NULL,nodes INTEGER NOT NULL,profile TEXT NOT NULL);
        """)
        with db: meta(db,"signature",signature)
        mapped,groups=group_mapping(db)
        with db: db.executemany("INSERT INTO group_map VALUES (?,?,?,?,?)",mapped)
        print("Mapped game families:",json.dumps(groups),flush=True)
        # Source v1 is small: force it to be the outer lookup rather than scanning
        # and sorting the entire 1.3M-label cache repeatedly.
        duplicates="""SELECT a.id,a.game_id,b.game_id,a.split,b.split,a.outcome,b.outcome,la.cp=lb.cp
          FROM v1.positions a CROSS JOIN v1_labels.labels la ON la.id=a.id AND la.profile=?
          CROSS JOIN v2.positions b ON b.id=a.id CROSS JOIN v2_labels.labels lb ON lb.id=b.id AND lb.profile=?
          WHERE la.cp IS NOT NULL AND lb.cp IS NOT NULL"""
        with db:
            db.execute("INSERT INTO duplicate_provenance "+duplicates,(profile,profile))
            db.execute("INSERT INTO exclusions SELECT id,CASE WHEN v1_outcome!=v2_outcome THEN 'conflicting game outcomes' "
                       "WHEN v1_split!=v2_split THEN 'conflicting frozen position splits' ELSE 'conflicting teacher cp' END "
                       "FROM duplicate_provenance WHERE v1_outcome!=v2_outcome OR v1_split!=v2_split OR cp_equal=0")
        base="""INSERT INTO records(id,fen,game_id,game_index,split,origin,original_game,source,
              source_ordinal,owner,ply,outcome,phase,category,flags,year,cp,mate,depth,nodes,profile) """
        definitions={
          "v2":("p.ordinal,NULL,p.ply,p.outcome,p.phase,p.category,p.flags,NULL", "v2_labels", "p.ordinal"),
          "v1":("NULL,NULL,p.ply,p.outcome,NULL,NULL,NULL,NULL", "v1_labels", "p.id"),
          "expanded":("p.ordinal,p.owner,p.ply,p.outcome,p.phase,p.category,p.flags,p.year", "expanded", "p.ordinal")}
        excluded_groups={};source_counts={};inserted={}
        for origin,(extra,label_alias,order) in definitions.items():
            where="l.cp IS NOT NULL AND l.profile=?"
            source_counts[origin]=db.execute(f"SELECT count(*) FROM {origin}.positions p CROSS JOIN {label_alias}.labels l "
                f"ON l.id=p.id AND l.profile=? WHERE l.cp IS NOT NULL",(profile,)).fetchone()[0]
            excluded_groups[origin]=db.execute(f"SELECT count(*) FROM {origin}.positions p CROSS JOIN {label_alias}.labels l "
                "ON l.id=p.id AND l.profile=? CROSS JOIN group_map g ON g.original_game=p.game_id "
                "WHERE l.cp IS NOT NULL AND g.quarantine=1",(profile,)).fetchone()[0]
            if origin=="expanded" and source_counts[origin]!=audit["quality"]["completed"]:
                raise ValueError("Expanded source count changed")
            print(f"Copying {origin}: {source_counts[origin]:,} compatible labeled positions",flush=True)
            if origin=="expanded":
                overlap=db.execute("SELECT count(*) FROM expanded.positions p CROSS JOIN records r ON r.id=p.id").fetchone()[0]
                if overlap:raise ValueError(f"Expanded corpus unexpectedly overlaps old labels: {overlap}")
            before=db.total_changes
            with db:
                db.execute(base+f"SELECT p.id,p.fen,g.game_id,g.game_index,p.split,?,p.game_id,p.source,{extra},"
                    f"l.cp,l.mate,l.depth,l.nodes,l.profile FROM {origin}.positions p "
                    f"CROSS JOIN {label_alias}.labels l ON l.id=p.id AND l.profile=? "
                    "CROSS JOIN group_map g ON g.original_game=p.game_id "
                    "WHERE l.cp IS NOT NULL AND g.quarantine=0 AND p.split=g.split "
                    "AND NOT EXISTS(SELECT 1 FROM exclusions e WHERE e.id=p.id) "
                    f"AND NOT EXISTS(SELECT 1 FROM records r WHERE r.id=p.id) ORDER BY {order}",(origin,profile))
            inserted[origin]=db.total_changes-before
            print(f"Copied {origin}: {inserted[origin]:,} unique records",flush=True)
        with db:
            db.execute("CREATE INDEX record_split ON records(split,ordinal)")
            db.execute("CREATE INDEX record_game ON records(game_id)")
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Merged database integrity failed")
        if db.execute("SELECT 1 FROM records GROUP BY game_id HAVING count(DISTINCT split)>1 LIMIT 1").fetchone():
            raise ValueError("Merged family crosses partitions")
        if db.execute("SELECT 1 FROM records WHERE outcome NOT IN (0,0.5,1) OR abs(cp)>32000 OR depth<1 OR nodes<1 "
                      "OR (mate IS NOT NULL AND cp!=CASE WHEN mate>0 THEN 2000 ELSE -2000 END) LIMIT 1").fetchone():
            raise ValueError("Merged labels violate their trained score contract")
        report={"utc":utc(),"source_counts":source_counts,"inserted_by_origin":inserted,"groups":groups,
                "excluded_family_positions":excluded_groups,"duplicates":db.execute("SELECT count(*) FROM duplicate_provenance").fetchone()[0],
                "excluded_position_ids":db.execute("SELECT count(*) FROM exclusions").fetchone()[0],
                "exclusions_by_reason":dict(db.execute("SELECT reason,count(*) FROM exclusions GROUP BY reason")),
                "positions":db.execute("SELECT count(*) FROM records").fetchone()[0],
                "splits":dict(db.execute("SELECT split,count(*) FROM records GROUP BY split")),
                "unique_positions":True,"grouped_splits_disjoint":True,"teacher_profile":profile,
                "duplicate_policy":"Same-FEN old rows are retained once; conflicting outcome, split or teacher-cp IDs are excluded from this derived corpus. No original record is modified.",
                "provenance":"records.origin/original_game/source_ordinal/owner link to the read-only source databases; duplicate_provenance retains both old game identities."}
        with db:meta(db,"report",report)
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    report["database_sha256"]=file_hash(path)
    atomic_json(destination/"merge-report.json",report)
    return report


def get_meta_from_alias(db, alias, key):
    row=db.execute(f"SELECT value FROM {alias}.metadata WHERE key=?",(key,)).fetchone()
    return json.loads(row[0]) if row else None


def encode_batch(rows: list[tuple]) -> tuple:
    """CPU-only preparation: no teacher processes, model imports or training."""
    n=len(rows)
    x=np.empty((n,2,37),np.uint16)
    y=np.empty((n,8),np.float32)
    ordinals=np.empty(n,np.int64)
    for i,(ordinal,pid,fen,cp,outcome,ply,phase,category,year,game_index,source,origin) in enumerate(rows):
        board=chess.Board(fen)
        if not board.is_valid() or board.chess960 or canonical_fen(board)!=fen or hashlib.sha256(fen.encode()).hexdigest()!=pid:
            raise ValueError(f"Invalid/corrupt merged FEN: {pid}")
        if origin!="expanded" and board.is_game_over():
            raise ValueError(f"Terminal old position: {pid}")
        pieces=board.piece_map()
        material=sum((1 if p.color==board.turn else -1)*(0,100,320,330,500,900,0)[p.piece_type] for p in pieces.values())
        if phase is None:
            nonpawn=sum((0,0,320,330,500,900,0)[p.piece_type] for p in pieces.values())
            phase="endgame" if len(pieces)<=10 or nonpawn<=2600 else "opening" if ply<=20 else "middlegame"
        if category is None:
            category="tactical_heuristic" if board.is_check() or any(board.generate_legal_captures()) else "quiet_heuristic"
        if year is None:
            years=re.findall(r"(?:19|20)\d{2}",Path(source).name)
            year=int(years[0]) if years else 0
        x[i]=encode(board)
        y[i]=(cp,outcome,material,ply,("opening","middlegame","endgame").index(phase),
              int(category=="tactical_heuristic"),year,game_index)
        ordinals[i]=ordinal
    return x,y,ordinals


def prepared_complete(path: Path) -> dict | None:
    manifest=path/"manifest.json"
    if not manifest.exists():return None
    report=json.loads(manifest.read_text(encoding="utf-8"))
    for name,expected in report["files"].items():
        if file_hash(path/name)!=expected:raise ValueError(f"Prepared file is corrupt: {path/name}")
    return report


def prepare_arrays(destination: Path, merged: dict, workers: int) -> dict:
    prepared=destination/"prepared"
    prepared.mkdir(exist_ok=True)
    ready={fmt:prepared_complete(prepared/fmt) for fmt in FORMATS}
    if all(ready.values()):return ready
    if any(ready.values()):
        raise ValueError("Only some feature formats are complete; keep them and use a fresh output")
    with closing(connect(destination/"merged.sqlite",readonly=True)) as db:
        groups={gid:index for gid,index in db.execute("SELECT DISTINCT game_id,game_index FROM records ORDER BY game_id")}
        for fmt in FORMATS:
            (prepared/fmt).mkdir(exist_ok=True)
            atomic_json(prepared/fmt/"game_ids.json",groups)
        reports={fmt:{"format":fmt,"feature_version":FEATURE_VERSION if fmt=="v2" else "halfkp64-10x64-shared-state12-v3",
            "king_buckets":None if fmt=="v2" else 16 if fmt=="v3-bucket16" else 64,
            "files":{},"splits":{},"y_columns":Y_COLUMNS,"source_database_sha256":merged["database_sha256"],
            "profile_id":merged["teacher_profile"],"grouped_splits_disjoint":True,
            "target":"0.9 * sigmoid(clip(stm_cp,-2000,2000)/400) + 0.1 * stm_outcome"} for fmt in FORMATS}
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for split in SPLITS:
                count=merged["splits"][split]
                if count<20:raise ValueError(f"Insufficient {split} examples")
                arrays={}
                for fmt in FORMATS:
                    shape=(count,2,37 if fmt=="v2" else 35)
                    arrays[fmt]=np.lib.format.open_memmap(prepared/fmt/f"{split}_x.npy.tmp",mode="w+",dtype=np.uint16,shape=shape)
                y=np.lib.format.open_memmap(prepared/"v2"/f"{split}_y.npy.tmp",mode="w+",dtype=np.float32,shape=(count,8))
                ordinals=np.lib.format.open_memmap(prepared/"v2"/f"{split}_ordinal.npy.tmp",mode="w+",dtype=np.int64,shape=(count,))
                cursor=db.execute("SELECT ordinal,id,fen,cp,outcome,ply,phase,category,year,game_index,source,origin "
                                  "FROM records WHERE split=? ORDER BY ordinal",(split,))
                pending=deque();written=0;exhausted=False;started=last_tick=time.monotonic()
                while pending or not exhausted:
                    while not exhausted and len(pending)<workers*2:
                        rows=[tuple(row) for row in cursor.fetchmany(4096)]
                        if rows:pending.append(pool.submit(encode_batch,rows))
                        else:exhausted=True
                    if not pending:break
                    x_chunk,y_chunk,ordinal_chunk=pending.popleft().result()
                    end=written+len(x_chunk)
                    arrays["v2"][written:end]=x_chunk
                    arrays["v3-bucket16"][written:end]=from_v2(x_chunk,16)
                    arrays["v3-full"][written:end]=from_v2(x_chunk,64)
                    y[written:end]=y_chunk;ordinals[written:end]=ordinal_chunk
                    written=end
                    if time.monotonic()-last_tick>=10:
                        rate=written/(time.monotonic()-started)
                        progress={"utc":utc(),"stage":"feature-preparation","split":split,"completed":written,
                                  "positions":count,"positions_per_second":rate,"eta_seconds":(count-written)/rate}
                        atomic_json(destination/"preparation-progress.json",progress)
                        print(f"Prepared {split}: {written:,}/{count:,}; {rate:.0f}/s; ETA {(count-written)/rate/60:.1f}m",flush=True)
                        last_tick=time.monotonic()
                if written!=count:raise ValueError("Prepared row count mismatch")
                for value in [*arrays.values(),y,ordinals]:
                    value.flush();value._mmap.close()
                for fmt in FORMATS:
                    directory=prepared/fmt
                    for kind in ("x","y","ordinal"):
                        temp=directory/f"{split}_{kind}.npy.tmp"
                        if fmt!="v2" and kind!="x":
                            shutil.copyfile(prepared/"v2"/f"{split}_{kind}.npy",temp)
                        with temp.open("r+b") as stream:os.fsync(stream.fileno())
                        name=f"{split}_{kind}.npy"
                        publish(temp,directory/name)
                        reports[fmt]["files"][name]=file_hash(directory/name)
                    reports[fmt]["splits"][split]={"positions":count,**{kind+"_sha256":reports[fmt]["files"][f"{split}_{kind}.npy"] for kind in ("x","y","ordinal")}}
                print(f"Prepared and checksummed {split}: {count:,} rows in all three feature formats",flush=True)
        # Verify independent board encoders and targets on a deterministic spread,
        # rather than accepting only agreement between derived representations.
        parity={}
        for fmt in FORMATS:
            checked=0;game_splits={}
            for split in SPLITS:
                directory=prepared/fmt
                x=np.load(directory/f"{split}_x.npy",mmap_mode="r")
                y=np.load(directory/f"{split}_y.npy",mmap_mode="r")
                orders=np.load(directory/f"{split}_ordinal.npy",mmap_mode="r")
                if not np.isfinite(y).all() or not np.all(y[:,7]==np.floor(y[:,7])):
                    raise ValueError("Nonfinite targets or fractional group indices")
                game_splits[split]=set(y[:,7].astype(np.int64))
                for index in np.unique(np.linspace(0,len(x)-1,min(256,len(x)),dtype=int)):
                    row=db.execute("SELECT * FROM records WHERE ordinal=?",(int(orders[index]),)).fetchone()
                    board=chess.Board(row["fen"])
                    expected=encode(board) if fmt=="v2" else encode_v3(board,16 if fmt=="v3-bucket16" else 64)
                    if not np.array_equal(x[index],expected) or tuple(y[index,:2])!=(row["cp"],row["outcome"]) or row["split"]!=split or y[index,7]!=row["game_index"]:
                        raise ValueError("Independent FEN/feature/target/group parity failed")
                    checked+=1
                x._mmap.close();y._mmap.close();orders._mmap.close()
            if any(game_splits[a]&game_splits[b] for a,b in (("train","validation"),("train","test"),("validation","test"))):
                raise ValueError("Prepared numeric game index leaks across splits")
            report=reports[fmt]
            report["independent_fens_checked"]=checked
            report["all_fens_canonical_and_ids_verified"]=True
            report["files"]["game_ids.json"]=file_hash(prepared/fmt/"game_ids.json")
            fingerprint=hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
            report["fingerprint"]=fingerprint
            atomic_json(prepared/fmt/"manifest.json",report)
            parity[fmt]=report
        return parity


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-run",type=Path,default=ROOT/"data/labeling/cc-events-v1")
    parser.add_argument("--output",type=Path,default=ROOT/"data/expanded/cc-events-20261016")
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--wait-for-source",action="store_true")
    parser.add_argument("--source-pid",type=int)
    args=parser.parse_args()
    run,destination=args.new_run.resolve(),args.output.resolve()
    labeling.output_guard(destination)
    if any(destination==p or destination in p.parents or p in destination.parents for p in [run,*sources(ROOT,run).values()]):
        raise ValueError("Output overlaps a preserved source")
    if not 1<=args.workers<=max(1,min(4,(os.cpu_count() or 2)//2)):
        raise ValueError("Feature encoding is capped at four conservative CPU workers")
    if destination.exists() and any(destination.iterdir()) and not args.resume:
        raise ValueError("Output exists; --resume verifies compatible completed stages")
    if shutil.disk_usage(destination.parent if destination.parent.exists() else ROOT).free<20*1024**3:
        raise ValueError("At least 20 GiB free disk is required")
    destination.mkdir(parents=True,exist_ok=True)
    while args.wait_for_source and not ((run/"validation.json").exists() and (run/"export/manifest.json").exists()):
        if args.source_pid:
            import psutil
            if not psutil.pid_exists(args.source_pid):
                raise ValueError("Labeling exited without completed validation/export; inspect its retained error log")
        print("Waiting for the existing labeling process to publish final validation/export; no labels are being changed",flush=True)
        time.sleep(30)
    with ExitStack() as stack:
        stack.enter_context(writer_lock(run))
        stack.enter_context(writer_lock(destination))
        audit_path=destination/"source-audit.json"
        if audit_path.exists():
            audit=json.loads(audit_path.read_text(encoding="utf-8"))
            if source_snapshot(sources(ROOT,run))!=audit["sources"]:
                raise ValueError("Preserved inputs changed after the saved audit")
        else:audit=readonly_audit(ROOT,run,destination,args.workers)
        merged=merge(ROOT,run,destination,audit)
        prepared=prepare_arrays(destination,merged,args.workers)
        after=source_snapshot(sources(ROOT,run))
        if after!=audit["sources"]:
            raise ValueError("An input changed during merging/preparation")
        result={"utc":utc(),"complete":True,"training_started":False,"source_files_unchanged":True,
                "merged":merged,"prepared":{k:{"fingerprint":v["fingerprint"],"splits":v["splits"]} for k,v in prepared.items()}}
        atomic_json(destination/"READY.json",result)
        print(json.dumps(result,indent=2),flush=True)


if __name__=="__main__":
    main()
