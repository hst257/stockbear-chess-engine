"""Architecture, legacy loading, development-only access and exact resume checks."""
import copy
import json

import numpy as np
import pytest
import torch

from stockbear import scaling_train as scaling
from stockbear.common import file_hash
from stockbear.model import NNUE


@pytest.mark.parametrize("width,hidden,count", [(32, 16, 26081), (64, 32, 54209), (128, 32, 108353)])
def test_shapes_counts_legacy_and_new_checkpoint_loading(width, hidden, count):
    model = NNUE(width, hidden)
    assert sum(p.numel() for p in model.parameters()) == count == scaling.architecture(width, hidden)["parameters"]
    x = torch.full((3, 2, 37), 780, dtype=torch.long)
    x[:, :, :3] = torch.tensor([0, 123, 765])
    assert model(x).shape == (3,)
    for metadata in ({}, {"model_config": {"width": width, "hidden": hidden},
                          "architecture": scaling.architecture(width, hidden)}):
        state = {"model": model.state_dict(), "format": "v2", **metadata}
        assert torch.equal(model(x), scaling.load_model(state)(x))
    with pytest.raises(ValueError, match="metadata"):
        scaling.load_model({"model": model.state_dict(), "model_config": {"width": width + 1, "hidden": hidden}})
    state = copy.deepcopy(model.state_dict())
    state["fc1.weight"] = torch.zeros(hidden, width)
    with pytest.raises(RuntimeError, match="size mismatch"):
        scaling.load_model({"model": state})


def prepared(tmp_path, monkeypatch):
    import hashlib
    directory = tmp_path / "data/expanded/mock/prepared/v2"
    directory.mkdir(parents=True)
    files, splits = {}, {}
    rng = np.random.default_rng(7)
    for split in ("train", "validation"):
        x = np.full((40, 2, 37), 780, dtype=np.uint16)
        x[:, :, :6] = rng.integers(0, 780, (40, 2, 6), dtype=np.uint16)
        y = np.zeros((40, 8), dtype=np.float32)
        y[:, 0] = rng.normal(0, 300, 40)
        y[:, 1] = rng.choice([0., .5, 1.], 40)
        for suffix, value in (("x", x), ("y", y), ("ordinal", np.arange(40))):
            name = f"{split}_{suffix}.npy"
            np.save(directory / name, value)
            files[name] = file_hash(directory / name)
        splits[split] = {"positions": 40}
    # A manifest may describe test data, but the files deliberately DO NOT EXIST.
    files["test_x.npy"] = "must-never-be-opened"
    manifest = {"format": "v2", "files": files, "splits": splits}
    manifest["fingerprint"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))
    (directory.parents[1] / "READY.json").write_text(json.dumps({
        "complete": True, "source_files_unchanged": True, "prepared": {"v2": manifest}}))
    monkeypatch.setattr(scaling, "ROOT", tmp_path)
    monkeypatch.setattr(scaling, "EXPERIMENT", tmp_path / "scaling-experiment-20261016")
    cfg = {"format": "v2", "dataset": str(directory), "seed": 7,
           "run": "scaling-experiment-20261016/artifacts/uninterrupted",
           "training": {"epochs": 3, "batch_size": 16, "width": 32, "hidden": 16,
                        "learning_rate": .0015, "weight_decay": .05, "teacher_weight": .9,
                        "patience": 8, "scheduler_patience": 2, "min_delta": .00001,
                        "gradient_clip": 1., "require_cuda": False}}
    return cfg, directory


def test_development_arrays_only_and_tamper_detection(tmp_path, monkeypatch):
    cfg, directory = prepared(tmp_path, monkeypatch)
    assert scaling.verify_dataset(cfg)[0] == directory
    with (directory / "validation_y.npy").open("r+b") as stream:
        stream.seek(-1, 2)
        stream.write(b"!")
    with pytest.raises(ValueError, match="checksum"):
        scaling.verify_dataset(cfg)


def test_resume_matches_uninterrupted_and_rejects_config_change(tmp_path, monkeypatch):
    # CPU fixture permits fast exact equality without depending on a GPU.
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    cfg, _ = prepared(tmp_path, monkeypatch)
    # The isolated ROOT has no sources; point signature paths at matching copies.
    from pathlib import Path
    original_root = Path(scaling.__file__).resolve().parents[1]
    (tmp_path / "stockbear").mkdir()
    for name in ("model.py", "train.py"):
        (tmp_path / "stockbear" / name).write_bytes((original_root / "stockbear" / name).read_bytes())
    # Signature uses the extension source; a synthetic ROOT requires a matching path.
    monkeypatch.setattr(scaling, "__file__", str(tmp_path / "stockbear/scaling_train.py"))
    (tmp_path / "stockbear/scaling_train.py").write_text("fixture source")
    assert scaling.fit(cfg)["complete"]
    a = torch.load(tmp_path / cfg["run"] / "final.pt", weights_only=False)
    cfg["run"] = "scaling-experiment-20261016/artifacts/resumed"
    assert not scaling.fit(cfg, stop_after=1)["complete"]
    assert scaling.fit(cfg, resume=True)["complete"]
    b = torch.load(tmp_path / cfg["run"] / "final.pt", weights_only=False)
    assert all(torch.equal(a["model"][k], b["model"][k]) for k in a["model"])
    assert [r["validation"] for r in a["history"]] == [r["validation"] for r in b["history"]]
    assert (tmp_path / cfg["run"] / "best.pt").is_file()
    assert (tmp_path / cfg["run"] / "raw_best.pt").is_file()
    cfg["training"]["learning_rate"] *= 2
    with pytest.raises(ValueError, match="identity mismatch"):
        scaling.fit(cfg, resume=True)
