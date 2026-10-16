"""Pipeline reliability tests use fake teachers; no expensive labeling/training."""
from contextlib import closing
import bz2
import gzip
import io
import json
import lzma
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import time
import zipfile

import chess
import chess.engine
import chess.pgn
import numpy as np
import pytest
import zstandard

from stockbear.common import digest
from stockbear.labeling.ingest import extract, finalize, ingest, inventory, pgn_text
from stockbear.labeling.output import export, prepare, validate
from stockbear.labeling.storage import (attach_existing, connect, counts, get_meta, initialize,
                                       set_meta, writer_lock)
from stockbear.labeling.teacher import convert_score, label
from stockbear.sample import canonical_fen, game_id, split_for


def game(seed=1, name="fixture", count=80):
    result = chess.pgn.Game()
    result.headers.update(Event=name,Date="2023.02.03",Round="1",White=f"Player {seed}",Black="Opponent",Result="1-0")
    rng,board,node = random.Random(seed),result.board(),result
    for _ in range(count):
        if board.is_game_over():
            break
        move = rng.choice(list(board.legal_moves))
        board.push(move)
        node = node.add_variation(move)
    outcome = board.outcome()
    if outcome:
        result.headers["Result"] = outcome.result()
    return result


def config():
    return {"seed":20261015,"min_ply":4,"max_ply":200,"ply_gap":2,"positions_per_game":12,
            "prefix_plies":20,"encoding":"utf-8-sig","limit":None,"workers":2,
            "max_attempts":3,"progress_seconds":1000}


def fixture(tmp_path, games=None, cfg=None, old_rows=(), old_games=()):
    raw,run = tmp_path/"raw",tmp_path/"run"
    raw.mkdir();run.mkdir()
    (raw/"input.pgn").write_text("\n\n".join(str(g) for g in (games or [game()]))+"\n",encoding="utf-8")
    old = tmp_path/"old.sqlite"
    with sqlite3.connect(old) as db:
        db.execute("CREATE TABLE positions(id TEXT PRIMARY KEY,fen TEXT,game_id TEXT,split TEXT)")
        db.execute("CREATE TABLE games(gid TEXT PRIMARY KEY,moves TEXT)")
        db.executemany("INSERT INTO positions VALUES (?,?,?,?)",old_rows)
        db.executemany("INSERT INTO games VALUES (?,?)",old_games)
    db = connect(run/"pipeline.sqlite")
    initialize(db)
    cfg = cfg or config()
    sources = inventory(raw)
    with db:
        set_meta(db,"profile_id","test-profile")
        set_meta(db,"profile",{"nodes":16384})
        set_meta(db,"teacher",{"id":{"name":"fake teacher, no engine launched"}})
        set_meta(db,"signature",{"sources":sources})
        db.executemany("INSERT INTO sources(id,path,sha256,bytes) VALUES (?,?,?,?)",
                       [(s["id"],s["path"],s["sha256"],s["bytes"]) for s in sources])
    return db,cfg,run,sources,attach_existing(db,[str(old)])


class FakeWorkers:
    calls = 0

    def __init__(self,cfg):
        pass

    def __call__(self,row):
        FakeWorkers.calls += 1
        return {"cp":43,"mate":None,"depth":8,"nodes":16384,"error":None}

    def close(self):
        pass


def build(db,cfg,sources,aliases):
    ingest(db,cfg,sources)
    finalize(db,cfg,aliases)


def test_label_resume_skips_completed_and_preserves_targets(tmp_path):
    db,cfg,run,sources,aliases = fixture(tmp_path)
    with closing(db):
        build(db,cfg,sources,aliases)
        FakeWorkers.calls = 0
        label(db,cfg,run,worker_factory=FakeWorkers)
        before = FakeWorkers.calls
        assert before==counts(db)["positions"]
        label(db,cfg,run,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==before
        result = validate(db,run,aliases)
        assert result["complete"] and result["original_corpus_overlap"]==0
        out = export(db,result,run/"export")
        assert export(db,result,run/"export")==out
        records = [json.loads(s) for s in (run/"export/records.jsonl").read_text().splitlines()]
        assert len(records)==before
        assert all(r["target"]==pytest.approx(.9/(1+np.exp(-43/400))+.1*r["outcome"]) for r in records)
        for features,width in (("v2",37),("v3-full",35),("v3-bucket16",35)):
            manifest = prepare(db,result,run/features,features)
            for split,r in manifest["splits"].items():
                assert np.load(run/features/f"{split}_x.npy").shape==(r["positions"],2,width)
                y = np.load(run/features/f"{split}_y.npy")
                assert y.shape==(r["positions"],8)
                assert not len(y) or (y[:,0]==43).all()


def test_ctrl_c_saves_inflight_and_resume_completes(tmp_path,monkeypatch):
    import stockbear.labeling.teacher as module
    db,cfg,run,sources,aliases = fixture(tmp_path)
    with closing(db):
        build(db,cfg,sources,aliases)
        original = module.wait
        def interrupt(*args,**kwargs):
            raise KeyboardInterrupt
        monkeypatch.setattr(module,"wait",interrupt)
        with pytest.raises(KeyboardInterrupt):
            label(db,cfg,run,worker_factory=FakeWorkers)
        committed = counts(db)["completed"]
        assert committed==2 and counts(db)["pending"]>0
        monkeypatch.setattr(module,"wait",original)
        label(db,cfg,run,worker_factory=FakeWorkers)
        assert counts(db)["remaining"]==0


def test_ingest_cursor_resumes_without_duplicate_games(tmp_path,monkeypatch):
    import stockbear.labeling.ingest as module
    db,cfg,run,sources,aliases = fixture(tmp_path,[game(1),game(2)])
    with closing(db):
        original = module.extract
        calls = 0
        def interrupt(*args):
            nonlocal calls
            calls += 1
            if calls==2:
                raise KeyboardInterrupt
            return original(*args)
        monkeypatch.setattr(module,"extract",interrupt)
        with pytest.raises(KeyboardInterrupt):
            ingest(db,cfg,sources)
        assert db.execute("SELECT cursor FROM sources").fetchone()[0]==1
        monkeypatch.setattr(module,"extract",original)
        build(db,cfg,sources,aliases)
        assert counts(db)["games"]==2
        assert db.execute("SELECT count(*) FROM (SELECT game,id,count(*) n FROM observations GROUP BY game,id HAVING n>1)").fetchone()[0]==0


def test_exact_dedup_and_move_alias_anchors_frozen_split(tmp_path):
    g = game()
    cfg = config()
    rows,moves,keys = extract(g,cfg)
    # Different headers but identical moves must still inherit the old frozen test split.
    old_gid = "frozen-group"
    first = rows[0][1]
    db,cfg,run,sources,aliases = fixture(tmp_path,[g],cfg,
        [(digest(first),first,old_gid,"test")],[(old_gid,moves)])
    with closing(db):
        build(db,cfg,sources,aliases)
        assert db.execute("SELECT count(*) FROM positions WHERE id=?",(digest(first),)).fetchone()[0]==0
        assert set(r[0] for r in db.execute("SELECT split FROM positions"))=={"test"}
        assert set(r[0] for r in db.execute("SELECT game_id FROM positions"))=={old_gid}


def test_conflicting_frozen_groups_quarantined_before_teacher(tmp_path):
    g = game()
    rows,moves,keys = extract(g,config())
    a,b = rows[:2]
    db,cfg,run,sources,aliases = fixture(tmp_path,[g],old_rows=[
        (digest(a[1]),a[1],"old-a","train"),(digest(b[1]),b[1],"old-b","test")],
        old_games=[("old-a",moves),("old-b",moves)])
    with closing(db):
        build(db,cfg,sources,aliases)
        assert counts(db)["positions"]==0
        assert get_meta(db,"sampling_report")["quarantined_families"]==1


def test_aliases_and_bounded_sampling_are_deterministic(tmp_path):
    a,b = game(),game()
    b.headers.update(Event="different snapshot",Date="2024.02.03",White="Alias",Black="Another alias")
    cfg = config();cfg["limit"] = 5
    db,cfg,run,sources,aliases = fixture(tmp_path,[a,b],cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        assert counts(db)["positions"]==5
        assert db.execute("SELECT count(DISTINCT group_id) FROM games").fetchone()[0]==1
        assert extract(a,cfg)==extract(a,cfg)
        assert len(extract(a,cfg)[0])<=cfg["positions_per_game"]


@pytest.mark.parametrize("format",["plain","gz","bz2","xz","zst","zip"])
def test_plain_and_compressed_inputs(tmp_path,format):
    payload = (str(game())+"\n").encode()
    if format=="plain":
        path = tmp_path/"input.pgn";path.write_bytes(payload)
    elif format=="gz":
        path = tmp_path/"input.pgn.gz";path.write_bytes(gzip.compress(payload))
    elif format=="zst":
        path = tmp_path/"input.pgn.zst";path.write_bytes(zstandard.ZstdCompressor().compress(payload))
    elif format=="bz2":
        path = tmp_path/"input.pgn.bz2";path.write_bytes(bz2.compress(payload))
    elif format=="xz":
        path = tmp_path/"input.pgn.xz";path.write_bytes(lzma.compress(payload))
    else:
        path = tmp_path/"input.zip"
        with zipfile.ZipFile(path,"w") as z:
            z.writestr("nested/game.pgn",payload)
    source = inventory(tmp_path)[0]
    with pgn_text(source,"utf-8-sig") as stream:
        assert chess.pgn.read_game(stream).headers["White"]=="Player 1"


def test_malformed_games_are_logged_without_labels(tmp_path):
    g = game();g.headers["Result"] = "*"
    db,cfg,run,sources,aliases = fixture(tmp_path,[g])
    with closing(db):
        build(db,cfg,sources,aliases)
        assert counts(db)["positions"]==0 and counts(db)["errors"]==1
        with pytest.raises(ValueError,match="No new positions"):
            validate(db,run,aliases)


def test_failed_teachers_exhaust_retries_and_manual_retry_retains_errors(tmp_path):
    class Broken(FakeWorkers):
        def __call__(self,row):
            return {"cp":None,"mate":None,"depth":None,"nodes":None,"error":"simulated engine crash"}
    cfg = config();cfg["limit"]=2
    db,cfg,run,sources,aliases = fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        with pytest.raises(RuntimeError,match="incomplete"):
            label(db,cfg,run,worker_factory=Broken)
        assert counts(db)["failed"]==2 and counts(db)["attempts"]==6
        assert counts(db)["errors"]==6
        partial = validate(db,run,aliases,allow_partial=True)
        assert not partial["complete"]
        label(db,cfg,run,retry_failed=True,worker_factory=FakeWorkers)
        assert counts(db)["remaining"]==0 and counts(db)["errors"]>=6


def test_score_conventions_and_exclusive_writer(tmp_path):
    assert convert_score(chess.engine.Cp(-2345))==(-2345,None)
    assert convert_score(chess.engine.Mate(5))==(2000,5)
    assert convert_score(chess.engine.Mate(-3))==(-2000,-3)
    assert split_for("same-group",20261015)==split_for("same-group",20261015)
    with writer_lock(tmp_path):
        with pytest.raises(RuntimeError,match="Another process"):
            with writer_lock(tmp_path):
                pass


def test_completed_export_corruption_is_rejected(tmp_path):
    db,cfg,run,sources,aliases = fixture(tmp_path)
    with closing(db):
        build(db,cfg,sources,aliases)
        label(db,cfg,run,worker_factory=FakeWorkers)
        result = validate(db,run,aliases)
        export(db,result,run/"export")
        (run/"export/records.jsonl").write_text("corrupt\n")
        with pytest.raises(ValueError,match="changed"):
            export(db,result,run/"export")


@pytest.mark.parametrize("fast_runtime",[False,True])
def test_hard_process_kill_reopens_wal_and_retries_only_pending(tmp_path,fast_runtime):
    db,cfg,run,sources,aliases = fixture(tmp_path)
    cfg.update(threads=1,hash_mb=64)
    build(db,cfg,sources,aliases)
    db.close()
    program = '''
import json,sys,time
from pathlib import Path
from stockbear.labeling.storage import connect,writer_lock
from stockbear.labeling.teacher import label
class Slow:
    def __init__(self,cfg): pass
    def __call__(self,row):
        time.sleep(.2)
        return dict(cp=43,mate=None,depth=8,nodes=16384,error=None)
    def close(self): pass
run=Path(sys.argv[1])
with writer_lock(run),connect(run/'pipeline.sqlite') as db:
    label(db,json.loads(sys.argv[2]),run,worker_factory=Slow)
'''
    if fast_runtime:
        program=program.replace("from stockbear.labeling.teacher import label",
                                "from stockbear.labeling_runtime import label_fast as label")
    flags = {"creationflags":subprocess.CREATE_NO_WINDOW} if sys.platform=="win32" else {}
    process = subprocess.Popen([sys.executable,"-c",program,str(run),json.dumps(cfg)],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**flags)
    try:
        end = time.monotonic()+10
        while time.monotonic()<end:
            with closing(connect(run/"pipeline.sqlite",readonly=True)) as reader:
                saved = counts(reader)["completed"]
            if saved>=2:
                break
            assert process.poll() is None
            time.sleep(.02)
        assert saved>=2
        process.kill();process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill();process.wait(timeout=5)
    with writer_lock(run), closing(connect(run/"pipeline.sqlite")) as reopened:
        saved = counts(reopened)["completed"]
        assert 0<saved<counts(reopened)["positions"]
        FakeWorkers.calls = 0
        label(reopened,cfg,run,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==counts(reopened)["positions"]-saved
        assert reopened.execute("PRAGMA integrity_check").fetchone()[0]=="ok"


def test_resume_rejects_changed_sources_configuration_and_oversubscription(tmp_path):
    from stockbear.labeling.__main__ import check_signature,configuration,parser,runtime
    from stockbear.labeling.storage import corpus_snapshot,source_hashes
    from stockbear.common import file_hash
    raw=tmp_path/"raw";raw.mkdir()
    (raw/"input.pgn").write_text(str(game()),encoding="utf-8")
    teacher=tmp_path/"teacher.exe";teacher.write_bytes(b"fixture, never executed")
    old=tmp_path/"old.sqlite";old.write_bytes(b"fixture corpus")
    arguments=["run","--input",str(raw),"--stockfish",str(teacher),"--existing-corpus",str(old)]
    cfg=configuration(parser().parse_args(arguments),None)
    signature={"version":1,"code":source_hashes(),"sources":inventory(raw),
        "existing_corpora":[corpus_snapshot(old)],"teacher_sha256":file_hash(teacher),"runtime":runtime()}
    check_signature(signature,cfg)
    with pytest.raises(ValueError,match="Configuration changed"):
        configuration(parser().parse_args(arguments+["--nodes","999"]),cfg)
    with pytest.raises(ValueError,match="Concurrency"):
        configuration(parser().parse_args(arguments+["--workers","100"]),None)
    with (raw/"input.pgn").open("a") as stream: stream.write("\n")
    with pytest.raises(ValueError,match="Input files changed"):
        check_signature(signature,cfg)


def test_illegal_pgn_is_skipped_and_next_game_survives(tmp_path):
    db,cfg,run,sources,aliases=fixture(tmp_path)
    with closing(db):
        source=Path(sources[0]["path"])
        text='[Event "illegal"]\n[Result "1-0"]\n\n1. e4 e5 2. Ke3 1-0\n\n'+str(game())+'\n'
        source.write_text(text,encoding="utf-8")
        sources=inventory(source.parent)
        build(db,cfg,sources,aliases)
        assert counts(db)["errors"]==1
        assert counts(db)["games"]==1
        assert counts(db)["positions"]>0
        assert db.execute("SELECT cursor FROM sources").fetchone()[0]==2


def test_header_movetext_result_conflict_is_not_labeled(tmp_path):
    db,cfg,run,sources,aliases=fixture(tmp_path)
    with closing(db):
        source=Path(sources[0]["path"])
        text=str(game()).rsplit("1-0",1)[0]+"0-1\n\n"
        source.write_text(text,encoding="utf-8")
        build(db,cfg,inventory(source.parent),aliases)
        assert counts(db)["positions"]==0
        assert "result conflict" in db.execute("SELECT message FROM errors").fetchone()[0]


def test_previous_pipeline_output_is_a_readonly_frozen_corpus(tmp_path):
    first=tmp_path/"first";first.mkdir()
    db,cfg,run,sources,aliases=fixture(first)
    with closing(db):
        build(db,cfg,sources,aliases)
        prior_split=db.execute("SELECT split FROM positions LIMIT 1").fetchone()[0]
    second=tmp_path/"second";second.mkdir()
    alias_game=game();alias_game.headers.update(Event="renamed",White="Alias",Date="2025.01.01")
    current,cfg,run2,sources,aliases=fixture(second,[alias_game])
    with closing(current):
        current.execute("ATTACH DATABASE ? AS previous",((run/"pipeline.sqlite").resolve().as_uri()+"?mode=ro",))
        build(current,cfg,sources,aliases+["previous"])
        assert counts(current)["positions"]>0
        assert set(r[0] for r in current.execute("SELECT split FROM positions"))=={prior_split}
        assert current.execute("SELECT count(*) FROM positions p JOIN previous.positions o ON p.id=o.id").fetchone()[0]==0


def test_fast_runtime_preserves_signature_and_skips_completed(tmp_path):
    from stockbear.labeling_runtime import label_fast
    cfg=dict(config(),threads=1,hash_mb=64)
    db,cfg,run,sources,aliases=fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        signature=get_meta(db,"signature")
        with db: set_meta(db,"config",cfg)
        FakeWorkers.calls=0
        result=label_fast(db,cfg,run,workers=4,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==counts(db)["positions"]
        assert result["execution"]["saved_workers"]==2
        assert result["execution"]["execution_workers"]==4
        assert get_meta(db,"config")==cfg and get_meta(db,"signature")==signature
        label_fast(db,cfg,run,workers=4,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==counts(db)["positions"]


def test_fast_keyset_retries_rows_behind_cursor(tmp_path):
    from stockbear.labeling_runtime import label_fast
    class Once(FakeWorkers):
        def __init__(self,cfg): self.attempts={}
        def __call__(self,row):
            attempt=self.attempts.get(row["id"],0)+1
            self.attempts[row["id"]]=attempt
            if attempt==1:
                return dict(cp=None,mate=None,depth=None,nodes=None,error="transient")
            return super().__call__(row)
    cfg=dict(config(),threads=1,hash_mb=64,limit=4)
    db,cfg,run,sources,aliases=fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        result=label_fast(db,cfg,run,worker_factory=Once)
        assert result["remaining"]==0 and result["attempts"]==8 and result["errors"]==4
        assert result["queue_calls"]<=3


def test_fast_interrupt_and_resume_derive_counters_from_commits(tmp_path,monkeypatch):
    import stockbear.labeling_runtime as fast
    cfg=dict(config(),threads=1,hash_mb=64)
    db,cfg,run,sources,aliases=fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        original_wait=fast.wait
        def interrupt(*args,**kwargs): raise KeyboardInterrupt
        monkeypatch.setattr(fast,"wait",interrupt)
        with pytest.raises(KeyboardInterrupt):
            fast.label_fast(db,cfg,run,worker_factory=FakeWorkers)
        assert counts(db)["completed"]==2
        monkeypatch.setattr(fast,"wait",original_wait)
        FakeWorkers.calls=0
        result=fast.label_fast(db,cfg,run,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==result["positions"]-2
        assert result["completed"]==result["positions"] and result["attempts"]==result["positions"]


def test_fast_sparse_ordinals_failed_rows_and_manual_retry(tmp_path):
    from stockbear.labeling_runtime import label_fast
    cfg=dict(config(),threads=1,hash_mb=64)
    db,cfg,run,sources,aliases=fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        with db:
            db.execute("UPDATE positions SET ordinal=ordinal*1000")
            db.execute("INSERT INTO labels(profile,id) SELECT 'test-profile',id FROM positions")
            db.execute("UPDATE labels SET cp=43,depth=8,nodes=16384,attempts=1 WHERE id IN (SELECT id FROM positions ORDER BY ordinal LIMIT 3)")
            failed=db.execute("SELECT id FROM positions ORDER BY ordinal LIMIT 1 OFFSET 3").fetchone()[0]
            db.execute("UPDATE labels SET failed=1,attempts=3,error='failed' WHERE id=?",(failed,))
        FakeWorkers.calls=0
        with pytest.raises(RuntimeError,match="incomplete"):
            label_fast(db,cfg,run,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==counts(db)["positions"]-4
        FakeWorkers.calls=0
        result=label_fast(db,cfg,run,retry_failed=True,worker_factory=FakeWorkers)
        assert FakeWorkers.calls==1 and result["remaining"]==0


def test_fast_progress_never_rescans_labels_per_update(tmp_path,monkeypatch):
    import stockbear.labeling_runtime as fast
    cfg=dict(config(),threads=1,hash_mb=64,progress_seconds=.00001)
    db,cfg,run,sources,aliases=fixture(tmp_path,cfg=cfg)
    with closing(db):
        build(db,cfg,sources,aliases)
        original_counts=fast.counts
        calls=[]
        def counted(db):
            calls.append(1)
            return original_counts(db)
        monkeypatch.setattr(fast,"counts",counted)
        result=fast.label_fast(db,cfg,run,worker_factory=FakeWorkers)
        assert result["remaining"]==0
        assert len(calls)==2  # Startup and final reconciliation, despite frequent progress.
