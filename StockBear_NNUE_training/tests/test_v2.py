import io
import json
import struct

import chess
import chess.pgn
import numpy as np
import pytest
import torch
import zstandard

from stockbear.common import connect,digest
from stockbear.features import FEATURES,PADDING,encode
from stockbear.model import NNUE
from stockbear.sample import pgn_stream
from stockbear.v2.data import classify,game_positions,inventory,build_pool
from stockbear.v2.label import ScaleWorker
from stockbear.v2.learn import statistics


def make_game(moves=None,event="test"):
    game=chess.pgn.Game()
    game.headers.update(Event=event,Date="2024.01.01",Round="1",White="A",Black="B",Result="1-0")
    board=game.board();node=game
    for uci in moves or ["e2e4","d7d5","e4d5","d8d5","b1c3","d5e5","g1e2","g8f6","a2a3"]:
        move=chess.Move.from_uci(uci)
        assert move in board.legal_moves
        board.push(move);node=node.add_variation(move)
    return game


def test_v2_zstd_skippable_and_multiframe(tmp_path):
    text=str(make_game())+"\n\n"
    payload=b"known standard skippable frame"
    data=struct.pack("<II",0x184D2A50,len(payload))+payload
    data+=zstandard.ZstdCompressor().compress(text.encode())
    data+=zstandard.ZstdCompressor().compress(text.encode())
    path=tmp_path/"sample.pgn.zst";path.write_bytes(data)
    with pgn_stream(path) as stream:
        assert chess.pgn.read_game(stream) is not None
        assert chess.pgn.read_game(stream) is not None
        assert chess.pgn.read_game(stream) is None


def test_v2_sampler_keeps_checks_captures_and_promotions():
    cfg={"seed":11,"min_ply":1,"max_ply":300,"ply_gap":1,"positions_per_game":16}
    game=make_game()
    rows,fingerprint=game_positions(game,cfg)
    assert any("in_check" in row[-1] for row in rows)
    assert any("after_capture" in row[-1] for row in rows)
    assert all(chess.Board(row[1]).is_valid() for row in rows)
    assert rows==game_positions(game,cfg)[0]
    board=chess.Board("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
    promoted=chess.pgn.Game();promoted.setup(board);promoted.headers["Result"]="1-0"
    promoted.add_variation(chess.Move.from_uci("a7a8q"))
    assert any("after_promotion" in row[-1] for row in game_positions(promoted,cfg)[0])


def test_v2_nested_pool_merges_move_aliases(tmp_path):
    raw=tmp_path/"data/raw";raw.mkdir(parents=True)
    text="\n\n".join(str(make_game(event=event)) for event in ("one","alias","other"))+"\n\n"
    (raw/"lichess_db_broadcast_2024-01.pgn.zst").write_bytes(zstandard.ZstdCompressor().compress(text.encode()))
    old=connect(tmp_path/"data/processed/full.sqlite")
    old.execute("CREATE TABLE positions(id TEXT,game_id TEXT,split TEXT)");old.commit();old.close()
    cfg={"reports":"reports/v2","pool":"data/v2/pool.sqlite","runs":"runs/v2","seed":5,"games_per_archive":20,
         "positions_per_game":16,"min_ply":1,"max_ply":300,"ply_gap":1}
    inventory(tmp_path,cfg)
    report=build_pool(tmp_path,cfg)
    assert report["merged_game_aliases"]==2
    db=connect(tmp_path/cfg["pool"])
    rows=db.execute("SELECT id,ordinal,game_id,split FROM positions ORDER BY ordinal").fetchall()
    assert [row[1] for row in rows]==list(range(1,len(rows)+1))
    assert len({row[2] for row in rows})==1
    assert len({row[3] for row in rows})==1
    assert {row[0] for row in rows[:3]}<={row[0] for row in rows[:6]}
    assert build_pool(tmp_path,cfg)==report
    db.close()


def test_v2_inventory_recovers_missing_selection_database(tmp_path):
    raw=tmp_path/'data/raw';raw.mkdir(parents=True)
    text='\n\n'.join(str(make_game(event=event)) for event in ('one','two','three'))+'\n\n'
    (raw/'lichess_db_broadcast_2024-01.pgn.zst').write_bytes(zstandard.ZstdCompressor().compress(text.encode()))
    cfg={'reports':'reports/v2','pool':'data/v2/pool.sqlite','seed':5,'games_per_archive':20}
    first=inventory(tmp_path,cfg)
    db=connect(tmp_path/cfg['pool'])
    expected=db.execute('SELECT source,gid FROM selected ORDER BY source,gid').fetchall()
    assert len(expected)==3
    db.execute('DELETE FROM selected');db.commit();db.close()
    recovered=inventory(tmp_path,cfg)
    db=connect(tmp_path/cfg['pool'])
    assert db.execute('SELECT source,gid FROM selected ORDER BY source,gid').fetchall()==expected
    assert recovered['source_signature']==first['source_signature']
    assert recovered['archives'][0]['selection_seed']==5
    db.close()


@pytest.mark.parametrize("width,hidden",[(32,16),(64,32),(128,32),(256,64)])
def test_v2_all_widths_forward_backward(width,hidden):
    model=NNUE(width,hidden)
    x=torch.from_numpy(np.stack([encode(chess.Board())]*2))
    loss=(model(x)-.7).square().mean();loss.backward()
    expected=(FEATURES+1)*width+width+2*width*hidden+2*hidden+1
    assert sum(p.numel() for p in model.parameters())==expected
    assert model.transform.weight.grad[PADDING].abs().sum()==0
    assert torch.isfinite(loss)


def test_v2_corrupt_record_never_reaches_engine(monkeypatch):
    worker=ScaleWorker(None,{"nodes":100})
    monkeypatch.setattr(worker,"engine",lambda:pytest.fail("Corrupt input must be rejected before analysis"))
    result=worker(("wrong hash",chess.STARTING_FEN,0))
    assert result[1] is None and "corrupt" in result[-1]


def test_v2_metric_definitions_and_json():
    cp=np.array([-2000,-500,-100,0,100,500,2000.],dtype=np.float32)
    y=np.zeros((len(cp),8),dtype=np.float32);y[:,0]=cp;y[:,1]=.5
    result=statistics(cp,y)
    assert result["teacher_probability_mse"]==0
    assert result["clipped_cp_mae"]==0
    assert result["sign_accuracy_abs_cp_ge_100"]==1
    assert abs(result["clipped_cp_pearson"]-1)<1e-10
    json.dumps(result,allow_nan=False)


@pytest.mark.skipif(not torch.cuda.is_available(),reason="CUDA unavailable")
def test_v2_resume_does_not_evaluate_test_set(tmp_path,monkeypatch):
    from stockbear.v2 import learn
    x=torch.from_numpy(np.stack([encode(chess.Board())]*24)).cuda()
    y=torch.zeros((24,8),device="cuda");y[:,1]=.5;y[:,6]=2025;y[:,7]=torch.arange(24,device="cuda")
    test_x=x.clone()
    data={"train":(x,y),"validation":(x.clone(),y.clone()),"test":(test_x,y.clone())}
    manifest={"fingerprint":"fixture"}
    monkeypatch.setattr(learn,"resident",lambda root,cfg,size:(data,tmp_path,manifest))
    original=learn.predict
    def guarded(model,features,*args,**kwargs):
        assert features.data_ptr()!=test_x.data_ptr()
        return original(model,features,*args,**kwargs)
    monkeypatch.setattr(learn,"predict",guarded)
    cfg={"seed":5,"runs":"runs","architectures":{"compact":[32,16]},"training":{
        "epochs":3,"batch_size":8,"learning_rate":.001,"weight_decay":.05,"teacher_weight":.9,
        "patience":5,"scheduler_patience":2,"min_delta":1e-8,"gradient_clip":1.0}}
    assert learn.fit(tmp_path,cfg,"resume",24,"compact",stop_after=1)["status"]=="checkpointed"
    report=learn.fit(tmp_path,cfg,"resume",24,"compact")
    assert report["epochs"]==3 and not report["test_evaluated"]
    assert "test" not in report["metrics"]
    assert not (tmp_path/"runs/resume/test_predictions.npy").exists()
