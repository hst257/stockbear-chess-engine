"""Verify merge exclusions, frozen groups and feature contracts without a teacher."""
from contextlib import closing
import hashlib
import json

import chess
import numpy as np
import pytest

from stockbear.common import file_hash
from stockbear.expanded_data import encode_batch, merge, prepare_arrays, prepared_complete, source_snapshot, sources, validate_fen_batch
from stockbear.labeling.storage import connect
from stockbear.sample import canonical_fen
from stockbear.v3.features import encode as encode_v3, from_v2


def fixture(tmp_path, conflicting_alias=False):
    root=tmp_path/"training";run=root/"data/labeling/finished"
    profile={"nodes":16384,"score_pov":"side_to_move","version":2}
    paths=sources(root,run)
    board=chess.Board();positions=[]
    for san in ("e4","e5","Nf3","Nc6","Bb5"):
        board.push_san(san);fen=canonical_fen(board)
        positions.append((hashlib.sha256(fen.encode()).hexdigest(),fen))
    for origin,path in paths.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        with closing(connect(path)) as db:
            db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
            if origin.endswith("labels") or origin=="expanded":
                db.execute("CREATE TABLE labels(profile TEXT,id TEXT,cp INTEGER,mate INTEGER,depth INTEGER,nodes INTEGER,PRIMARY KEY(profile,id))")
                db.execute("INSERT INTO metadata VALUES (?,?)",("profile:teacher",json.dumps(profile)))
            if origin in ("v1","v2","expanded"):
                db.execute("CREATE TABLE positions(id TEXT PRIMARY KEY,fen TEXT,game_id TEXT,split TEXT,source TEXT,ply INTEGER,outcome REAL,phase TEXT,category TEXT,flags TEXT,ordinal INTEGER,owner TEXT,year INTEGER)")
            if origin=="v2":
                db.execute("CREATE TABLE games(gid TEXT,moves TEXT)")
                db.executemany("INSERT INTO games VALUES (?,?)",[("A","moves-A"),("B","moves-A" if conflicting_alias else "moves-B")])
            if origin=="expanded":
                db.execute("CREATE TABLE groups(id TEXT,split TEXT,quarantine TEXT,anchors TEXT)")
                db.execute("INSERT INTO groups VALUES ('N','validation',NULL,?)",(json.dumps([["validation","C"]]),))
                db.execute("CREATE TABLE games(id TEXT,group_id TEXT)")
                db.execute("CREATE TABLE game_keys(game TEXT,key TEXT)")
                db.execute("CREATE TABLE prior_keys(key TEXT,gid TEXT,split TEXT)")
                db.execute("CREATE TABLE observations(id TEXT,game TEXT,ply INTEGER)")
                db.execute("CREATE TABLE existing_hits(id TEXT,gid TEXT,split TEXT)")
            db.commit()
    definitions={"v2":[(0,"A","train",1),(1,"A","train",1),(2,"A","train",1)],
                 "v1":[(0,"A","train",1),(1,"A","train",0),(2,"B","test",1),(3,"B","test",.5)],
                 "expanded":[(4,"N","validation",.5)]}
    for origin,rows in definitions.items():
        with closing(connect(paths[origin])) as db,closing(connect(paths[origin+"_labels"] if origin!="expanded" else paths[origin])) as labels:
            for i,gid,split,outcome in rows:
                pid,fen=positions[i]
                db.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pid,fen,gid,split,"example-2026.pgn",i+1,outcome,"opening","quiet_heuristic","",i+1,"owner",2026))
                db.commit()
                labels.execute("INSERT INTO labels VALUES ('teacher',?,10,NULL,8,16384)",(pid,))
                labels.commit()
    output=root/"data/expanded/new";output.mkdir(parents=True)
    audit={"sources":source_snapshot(paths),"profile_id":"teacher","profile":profile,"quality":{"completed":1}}
    return root,run,output,audit,positions


def test_merge_excludes_ambiguous_duplicates_and_preserves_sources(tmp_path):
    root,run,out,audit,positions=fixture(tmp_path)
    result=merge(root,run,out,audit)
    assert result["positions"]==3 and result["duplicates"]==3 and result["excluded_position_ids"]==2
    assert result["splits"]=={"train":1,"validation":1,"test":1}
    with closing(connect(out/"merged.sqlite",readonly=True)) as db:
        assert {row[0] for row in db.execute("SELECT id FROM records")}=={positions[i][0] for i in (0,3,4)}
        assert dict(db.execute("SELECT original_game,game_id FROM group_map"))["N"]=="C"
    assert source_snapshot(sources(root,run))==audit["sources"]
    assert merge(root,run,out,audit)==result


def test_merge_quarantines_conflicting_frozen_mainline_aliases(tmp_path):
    root,run,out,audit,_=fixture(tmp_path,True)
    result=merge(root,run,out,audit)
    assert result["positions"]==1 and result["splits"]=={"validation":1}
    assert result["groups"]["conflicting_split_families"]==1


def test_encoded_targets_and_both_v3_contracts_match_independent_boards():
    board=chess.Board();board.push_san("e4")
    fen=canonical_fen(board);pid=hashlib.sha256(fen.encode()).hexdigest()
    row=(1,pid,fen,83,.5,1,None,None,None,13,"example-2026.pgn","v1")
    x,y,ordinal=encode_batch([row])
    assert tuple(y[0,[0,1,6,7]])==(83,.5,2026,13) and ordinal[0]==1
    for bucket in (16,64):
        assert np.array_equal(from_v2(x,bucket)[0],encode_v3(board,bucket))
    with pytest.raises(ValueError,match="corrupt"):
        encode_batch([(1,"wrong",*row[2:])])


def test_all_prepared_formats_publish_and_load_without_training(tmp_path,monkeypatch):
    import random
    from stockbear import expanded_train
    destination=tmp_path/"data/expanded/example";destination.mkdir(parents=True)
    with closing(connect(destination/"merged.sqlite")) as db:
        db.execute("CREATE TABLE records(ordinal INTEGER PRIMARY KEY,id TEXT UNIQUE,fen TEXT,cp INTEGER,outcome REAL,"
                   "ply INTEGER,phase TEXT,category TEXT,year INTEGER,game_index INTEGER,source TEXT,origin TEXT,game_id TEXT,split TEXT)")
        board=chess.Board();rng=random.Random(94);seen=set();order=0
        for group,split in enumerate(("train","validation","test")):
            for i in range(24):
                while True:
                    if board.is_game_over():board=chess.Board()
                    board.push(rng.choice(list(board.legal_moves)))
                    fen=canonical_fen(board)
                    if fen not in seen and not board.is_game_over():break
                seen.add(fen);order+=1
                db.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (order,hashlib.sha256(fen.encode()).hexdigest(),fen,91,.5,i+1,"middlegame",
                     "quiet_heuristic",2026,group,"source.pgn","v2",str(group),split))
        db.commit()
    merged={"database_sha256":file_hash(destination/"merged.sqlite"),"teacher_profile":"teacher",
            "splits":{"train":24,"validation":24,"test":24}}
    result=prepare_arrays(destination,merged,workers=1)
    for fmt in result:
        assert prepared_complete(destination/"prepared"/fmt)["independent_fens_checked"]==72
        for split in merged["splits"]:
            assert result[fmt]["splits"][split]["y_sha256"]==result["v2"]["splits"][split]["y_sha256"]
            assert result[fmt]["splits"][split]["ordinal_sha256"]==result["v2"]["splits"][split]["ordinal_sha256"]
    ready={"complete":True,"source_files_unchanged":True,"prepared":result}
    (destination/"READY.json").write_text(json.dumps(ready),encoding="utf-8")
    monkeypatch.setattr(expanded_train,"ROOT",tmp_path)
    for fmt in result:
        _,manifest=expanded_train.verify_dataset({"dataset":"data/expanded/example/prepared/"+fmt,"format":fmt})
        assert manifest["splits"]["train"]["positions"]==24
    with (destination/"prepared/v2/train_x.npy").open("r+b") as stream:
        stream.seek(-1,2);stream.write(b"!")
    with pytest.raises(ValueError,match="corrupt"):
        prepared_complete(destination/"prepared/v2")


def test_readonly_fen_verification_rejects_corruption_and_terminal_boards():
    board=chess.Board();fen=canonical_fen(board)
    pid=hashlib.sha256(fen.encode()).hexdigest()
    assert validate_fen_batch([(pid,fen)])==1
    with pytest.raises(ValueError,match="source position"):
        validate_fen_batch([("wrong",fen)])
    for san in ("f3","e5","g4","Qh4#"):board.push_san(san)
    fen=canonical_fen(board)
    with pytest.raises(ValueError,match="source position"):
        validate_fen_batch([(hashlib.sha256(fen.encode()).hexdigest(),fen)])
