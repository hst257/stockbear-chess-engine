import json

from stockbear.common import connect
from stockbear.teacher import label


def test_label_cache_resume_and_profile_isolation(tmp_path, monkeypatch):
    import stockbear.teacher as teacher
    cfg = {"cache": "cache.sqlite", "dataset": "corpus.sqlite", "run": "run",
           "teacher": {"workers": 1, "nodes": 100, "hash_mb": 1}}
    db = connect(tmp_path / cfg["dataset"])
    db.execute("CREATE TABLE positions(id TEXT PRIMARY KEY, fen TEXT)")
    db.executemany("INSERT INTO positions VALUES (?,?)", [(str(i), "unused") for i in range(5)])
    db.commit()
    db.close()
    monkeypatch.setattr(teacher, "find_teacher", lambda root: root / "fake.exe")
    monkeypatch.setattr(teacher, "teacher_profile", lambda root, config: {"nodes": config["teacher"]["nodes"]})

    class FakeWorker:
        def __init__(self, exe, profile):
            pass
        def __call__(self, row):
            pid, fen, attempts = row
            return pid, 25, None, 4, 100, attempts + 1, None
        def close(self):
            pass
    monkeypatch.setattr(teacher, "Worker", FakeWorker)
    first = label(tmp_path, cfg, limit=2)
    assert first["new_labels"] == 2 and first["remaining"] == 3
    second = label(tmp_path, cfg)
    assert second["new_labels"] == 3 and second["remaining"] == 0
    assert label(tmp_path, cfg)["new_labels"] == 0
    cfg["teacher"]["nodes"] = 200
    assert label(tmp_path, cfg)["new_labels"] == 5
