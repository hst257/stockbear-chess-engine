import json

import chess
import pytest

from stockbear.common import connect, digest
from stockbear.sample import canonical_fen
from stockbear.validate import validate


def fixture_dataset(root, monkeypatch):
    import stockbear.validate as validation
    cfg = {"dataset": "data.sqlite", "cache": "cache.sqlite", "run": "run"}
    profile = {"fixture": 1}
    profile_id = digest(json.dumps(profile, sort_keys=True))
    monkeypatch.setattr(validation, "teacher_profile", lambda root, config: profile)
    monkeypatch.setattr(validation, "find_teacher", lambda root: root / "unused.exe")
    board = chess.Board()
    fen1 = canonical_fen(board)
    board.push_uci("e2e4")
    fen2 = canonical_fen(board)
    db = connect(root / "data.sqlite")
    db.execute("CREATE TABLE positions (id TEXT PRIMARY KEY, fen TEXT, game_id TEXT, split TEXT)")
    db.executemany("INSERT INTO positions VALUES (?,?,?,?)", [(digest(fen1), fen1, "game1", "train"), (digest(fen2), fen2, "game2", "test")])
    db.commit()
    db.close()
    cache = connect(root / "cache.sqlite")
    cache.execute("CREATE TABLE labels (profile TEXT, id TEXT, cp INTEGER, mate INTEGER, depth INTEGER, nodes INTEGER)")
    cache.executemany("INSERT INTO labels VALUES (?,?,?,?,?,?)", [(profile_id, digest(fen), 0, None, 1, 100) for fen in (fen1, fen2)])
    cache.commit()
    cache.close()
    return cfg


def test_validation_checks_canonical_fens_and_no_overlap(tmp_path, monkeypatch):
    cfg = fixture_dataset(tmp_path, monkeypatch)
    report = validate(tmp_path, cfg, repeat_teacher=0)
    assert report["canonical_positions_checked"] == 2
    db = connect(tmp_path / "data.sqlite")
    db.execute("UPDATE positions SET game_id='game1'")
    db.commit()
    db.close()
    with pytest.raises(AssertionError, match="game overlap=1"):
        validate(tmp_path, cfg, repeat_teacher=0)


def test_validation_rejects_missing_labels(tmp_path, monkeypatch):
    cfg = fixture_dataset(tmp_path, monkeypatch)
    cache = connect(tmp_path / "cache.sqlite")
    cache.execute("DELETE FROM labels")
    cache.commit()
    cache.close()
    with pytest.raises(AssertionError, match="missing=2"):
        validate(tmp_path, cfg, repeat_teacher=0)
