"""Exhaustive validation, portable records and existing NNUE array contracts."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3

import chess
import numpy as np

from ..common import digest, file_hash
from ..features import FEATURE_VERSION, MAX_ACTIVE, encode
from ..sample import canonical_fen
from ..v3.features import encode as encode_v3, from_v2
from .storage import SPLITS, atomic_json, counts, get_meta, publish, utc


def labeled_rows(db: sqlite3.Connection) -> sqlite3.Cursor:
    return db.execute("SELECT p.*,l.cp,l.mate,l.depth,l.nodes,l.profile,g.headers,g.source_id,g.number "
        "FROM positions p JOIN labels l USING(id) JOIN games g ON p.owner=g.id "
        "WHERE l.cp IS NOT NULL ORDER BY p.ordinal")


def validate(db: sqlite3.Connection, directory: Path, aliases: list[str], allow_partial: bool = False) -> dict:
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or list(db.execute("PRAGMA foreign_key_check")):
        raise ValueError("SQLite integrity/foreign-key check failed")
    if not get_meta(db,"planned") or db.execute("SELECT count(*) FROM sources WHERE complete=0").fetchone()[0]:
        raise ValueError("Ingestion/planning has not completed")
    report = counts(db)
    if not report["positions"]:
        raise ValueError("No new positions survived sampling/deduplication")
    if not allow_partial and report["remaining"]:
        raise ValueError(f"{report['remaining']} positions have no valid labels; output is incomplete")
    profile = get_meta(db,"profile_id")
    if db.execute("SELECT count(*) FROM labels WHERE profile!=?",(profile,)).fetchone()[0]:
        raise ValueError("Mixed teacher profiles")
    if db.execute("SELECT count(*) FROM (SELECT game_id FROM positions GROUP BY game_id HAVING count(DISTINCT split)>1)").fetchone()[0]:
        raise ValueError("Game-family split leakage")
    if db.execute("SELECT count(*) FROM positions p JOIN groups g ON p.game_id=g.id "
                  "WHERE g.quarantine IS NOT NULL OR p.split!=g.split").fetchone()[0]:
        raise ValueError("Invalid/quarantined game family exported")
    if db.execute("SELECT count(*) FROM (SELECT k.key FROM game_keys k JOIN games g ON k.game=g.id "
                  "JOIN groups f ON g.group_id=f.id WHERE f.quarantine IS NULL "
                  "GROUP BY k.key HAVING count(DISTINCT g.split)>1)").fetchone()[0]:
        raise ValueError("Game-alias split leakage")
    for alias in aliases:
        if db.execute(f"SELECT count(*) FROM positions p CROSS JOIN {alias}.positions o ON p.id=o.id").fetchone()[0]:
            raise ValueError("Position leaked from the frozen corpus")
    fingerprint = hashlib.sha256()
    cp_min,cp_max = None,None
    mate_labels = 0
    for row in db.execute("SELECT * FROM positions ORDER BY ordinal"):
        board = chess.Board(row["fen"])
        if not board.is_valid() or board.is_game_over() or canonical_fen(board)!=row["fen"] or digest(row["fen"])!=row["id"]:
            raise ValueError(f"Illegal/noncanonical position: {row['id']}")
        if row["outcome"] not in (0.0,0.5,1.0) or row["split"] not in SPLITS:
            raise ValueError("Invalid outcome/split metadata")
        fingerprint.update(json.dumps(dict(row),sort_keys=True).encode())
    for row in labeled_rows(db):
        cp,mate,depth,nodes = row["cp"],row["mate"],row["depth"],row["nodes"]
        if not isinstance(cp,int) or abs(cp)>32000 or not isinstance(depth,int) or depth<1 or not isinstance(nodes,int) or nodes<1:
            raise ValueError("Invalid label range or search metadata")
        if mate is not None and (not isinstance(mate,int) or cp!=(2000 if mate>0 else -2000)):
            raise ValueError("Invalid mate-to-cp conversion")
        headers = json.loads(row["headers"])
        white_outcome = {"1-0":1.,"0-1":0.,"1/2-1/2":.5}[headers["Result"]]
        stm = white_outcome if chess.Board(row["fen"]).turn else 1-white_outcome
        if stm != row["outcome"]:
            raise ValueError("Game result perspective mismatch")
        fingerprint.update(json.dumps({k:row[k] for k in ("id","profile","cp","mate","depth","nodes")},sort_keys=True).encode())
        cp_min = cp if cp_min is None else min(cp_min,cp)
        cp_max = cp if cp_max is None else max(cp_max,cp)
        mate_labels += int(mate is not None)
    report.update(utc=utc(),complete=report["remaining"]==0,unique_positions=report["positions"],
                  cp_min=cp_min,cp_max=cp_max,mate_labels=mate_labels,profile_id=profile,
                  fingerprint=fingerprint.hexdigest(),all_fens_and_labels_checked=True,
                  grouped_splits_disjoint=True,original_corpus_overlap=0,
                  splits=dict(db.execute("SELECT split,count(*) FROM positions GROUP BY split")),
                  sampling=get_meta(db,"sampling_report"))
    atomic_json(directory/"validation.json",report)
    atomic_json(directory/"manifest.json",{"schema":1,"signature":get_meta(db,"signature"),
        "teacher":get_meta(db,"teacher"),"teacher_profile":get_meta(db,"profile"),"validation":report,
        "target":"0.9 * sigmoid(clip(stm_cp,-2000,2000)/400) + 0.1 * stm_game_outcome",
        "nonmate_cp":"Stored without clipping, as in v2; clipping occurs only for training targets/metrics",
        "partial":not report["complete"]})
    return report


def destination(path: Path, signature: dict) -> bool:
    """Own incomplete outputs by a marker; publish the manifest only after all files."""
    marker = path/".export-owner.json"
    manifest = path/"manifest.json"
    if path.exists() and any(path.iterdir()):
        if not marker.exists() or json.loads(marker.read_text(encoding="utf-8")) != signature:
            raise ValueError(f"Destination is nonempty or belongs to another snapshot: {path}")
        if manifest.exists():
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            for name,sha in saved["files"].items():
                if file_hash(path/name)!=sha:
                    raise ValueError(f"Completed export changed: {path/name}")
            return True
    path.mkdir(parents=True,exist_ok=True)
    atomic_json(marker,signature)
    return False


def export(db: sqlite3.Connection, validation: dict, path: Path) -> dict:
    signature = {"dataset":validation["fingerprint"],"format":"stockbear-label-jsonl-v1"}
    if destination(path,signature):
        return json.loads((path/"manifest.json").read_text(encoding="utf-8"))
    files = {}
    queries = {"records.jsonl":None,"games.jsonl":"SELECT * FROM games ORDER BY id",
               "observations.jsonl":"SELECT * FROM observations ORDER BY game,id",
               "errors.jsonl":"SELECT * FROM errors ORDER BY sequence"}
    for name,query in queries.items():
        temporary = path/(name+".tmp")
        rows = labeled_rows(db) if query is None else db.execute(query)
        with temporary.open("w",encoding="utf-8",newline="\n") as stream:
            for row in rows:
                record = dict(row)
                if "headers" in record:
                    record["headers"] = json.loads(record["headers"])
                if query is None:
                    teacher = 1/(1+math.exp(-max(-2000,min(2000,row["cp"]))/400))
                    record["teacher_probability"] = teacher
                    record["target"] = .9*teacher+.1*row["outcome"]
                stream.write(json.dumps(record,sort_keys=True,allow_nan=False)+"\n")
            stream.flush();os.fsync(stream.fileno())
        publish(temporary,path/name)
        files[name] = file_hash(path/name)
    report = {"signature":signature,"validation":validation,"files":files,
              "source_inventory":get_meta(db,"signature")["sources"],
              "teacher":get_meta(db,"teacher"),"profile":get_meta(db,"profile"),
              "provenance":"records.owner -> games.id; observations retains all sampled game occurrences, including exclusions"}
    atomic_json(path/"manifest.json",report)
    return report


def prepare(db: sqlite3.Connection, validation: dict, path: Path, features: str) -> dict:
    signature = {"dataset":validation["fingerprint"],"format":features,"version":1}
    if destination(path,signature):
        return json.loads((path/"manifest.json").read_text(encoding="utf-8"))
    groups = {g:i for i,(g,) in enumerate(db.execute("SELECT DISTINCT game_id FROM positions ORDER BY game_id"))}
    if len(groups)>=2**24:
        raise ValueError("Float32 game-index column would lose integer precision")
    bucket = 16 if features=="v3-bucket16" else 64
    width = MAX_ACTIVE if features=="v2" else 35
    files,splits = {},{}
    for split in SPLITS:
        count = db.execute("SELECT count(*) FROM positions p JOIN labels l USING(id) "
                           "WHERE p.split=? AND l.cp IS NOT NULL",(split,)).fetchone()[0]
        rows = db.execute("SELECT p.*,l.cp FROM positions p JOIN labels l USING(id) "
                          "WHERE p.split=? AND l.cp IS NOT NULL ORDER BY ordinal",(split,))
        arrays = {"x":((count,2,width),np.uint16),"y":((count,8),np.float32),"ordinal":((count,),np.int64)}
        values = {}
        for kind,(shape,dtype) in arrays.items():
            temp = path/f"{split}_{kind}.npy.tmp"
            if count:
                values[kind] = np.lib.format.open_memmap(temp,mode="w+",dtype=dtype,shape=shape)
            else:
                values[kind] = np.empty(shape,dtype=dtype)
                with temp.open("wb") as stream:
                    np.save(stream,values[kind],allow_pickle=False)
        for i,row in enumerate(rows):
            board = chess.Board(row["fen"])
            x = encode(board).astype(np.uint16)
            values["x"][i] = x if features=="v2" else encode_v3(board,bucket)
            if features!="v2" and not np.array_equal(values["x"][i],from_v2(x[None],bucket)[0]):
                raise ValueError("Cross-version feature conversion mismatch")
            material = sum((1 if pc.color==board.turn else -1)*[0,100,320,330,500,900,0][pc.piece_type]
                           for pc in board.piece_map().values())
            values["y"][i] = (row["cp"],row["outcome"],material,row["ply"],
                ("opening","middlegame","endgame").index(row["phase"]),
                int(row["category"]=="tactical_heuristic"),row["year"],groups[row["game_id"]])
            values["ordinal"][i] = row["ordinal"]
        for kind in arrays:
            if count:
                values[kind].flush()
            # Close Windows mappings before atomic publication.
            if isinstance(values[kind],np.memmap):
                values[kind]._mmap.close()
            temp = path/f"{split}_{kind}.npy.tmp"
            with temp.open("r+b") as stream:
                os.fsync(stream.fileno())
            name = f"{split}_{kind}.npy"
            publish(temp,path/name)
            files[name] = file_hash(path/name)
        splits[split] = {"positions":count,"x_sha256":files[f"{split}_x.npy"],"y_sha256":files[f"{split}_y.npy"]}
    atomic_json(path/"game_ids.json",groups)
    files["game_ids.json"] = file_hash(path/"game_ids.json")
    report = {"signature":signature,"files":files,"splits":splits,"feature_version":FEATURE_VERSION if features=="v2" else "halfkp64-10x64-shared-state12-v3",
              "king_buckets":None if features=="v2" else bucket,"grouped_splits_disjoint":True,
              "y_columns":["stm_cp","stm_outcome","stm_material","ply","phase_index","tactical_heuristic","year_or_0","game_index"],
              "warning":"Same array contract as v2/v3; do not concatenate local numeric game indices across datasets. Merge by game_ids.json and frozen split identities first. No training was started.",
              "validation":validation}
    atomic_json(path/"manifest.json",report)
    return report
