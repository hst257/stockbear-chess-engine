import copy

import numpy as np
import torch

from stockbear.features import encode
from stockbear.model import NNUE
from stockbear.train import atomic_checkpoint, seed_everything, target


def test_training_checkpoint_resume_exact(tmp_path):
    import chess
    seed_everything(38)
    x = torch.from_numpy(np.stack([encode(chess.Board())] * 8))
    y = torch.tensor([[100.0, 1.0, 0, 20]] * 8)
    uninterrupted = NNUE(16, 8)
    opt = torch.optim.AdamW(uninterrupted.parameters(), lr=0.003)

    def step(model, optimizer):
        optimizer.zero_grad(set_to_none=True)
        loss = (model(x).sigmoid() - target(y, 0.9)).square().mean()
        loss.backward()
        optimizer.step()

    step(uninterrupted, opt)
    path = tmp_path / "last.pt"
    atomic_checkpoint(path, {"model": uninterrupted.state_dict(), "optimizer": opt.state_dict()})
    step(uninterrupted, opt)
    restored = NNUE(16, 8)
    restored_opt = torch.optim.AdamW(restored.parameters(), lr=0.003)
    checkpoint = torch.load(path, weights_only=False)
    restored.load_state_dict(checkpoint["model"])
    restored_opt.load_state_dict(checkpoint["optimizer"])
    step(restored, restored_opt)
    for name, tensor in uninterrupted.state_dict().items():
        torch.testing.assert_close(tensor, restored.state_dict()[name], rtol=0, atol=0)


def test_training_loop_resume_matches_uninterrupted(tmp_path, monkeypatch):
    import chess
    import importlib
    import json
    training = importlib.import_module("stockbear.train")
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    board = chess.Board()
    board.push_uci("e2e4")
    features = np.stack([encode(board)] * 24)
    labels = np.array([[75, 0.5, 0, 25]] * 24, dtype=np.float32)
    for split in ("train", "validation", "test"):
        np.save(prepared / f"{split}_x.npy", features)
        np.save(prepared / f"{split}_y.npy", labels)
        (prepared / f"{split}_rows.jsonl").write_text("\n".join(json.dumps({"id": str(i), "fen": board.fen(), "source": "fixture"}) for i in range(24)))
    monkeypatch.setattr(training, "prepare", lambda root, cfg: (prepared, {"fingerprint": "fixture", "profile_id": "fake"}))
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    tc = {"width": 16, "hidden": 8, "epochs": 4, "batch_size": 8, "learning_rate": 0.003,
          "weight_decay": 0.01, "teacher_weight": 0.9, "gradient_clip": 1.0,
          "patience": 8, "min_delta": 1e-8, "require_cuda": False}
    cfg = {"seed": 55, "training": tc, "run": "resumed"}
    training.train(tmp_path, cfg, stop_after=2)
    training.train(tmp_path, cfg, resume=True)
    cfg["run"] = "straight"
    validation_report = training.train(tmp_path, cfg, validation_only=True)
    assert set(validation_report["metrics"]) == {"train", "validation"}
    assert not (tmp_path / "straight/test_predictions.npy").exists()
    resumed = torch.load(tmp_path / "resumed/last.pt", weights_only=False)
    straight = torch.load(tmp_path / "straight/last.pt", weights_only=False)
    for name, tensor in straight["model"].items():
        torch.testing.assert_close(tensor, resumed["model"][name], rtol=0, atol=0)
    assert resumed["best"] == straight["best"]
    cfg["training"] = {**tc, "learning_rate": 0.01}
    import pytest
    with pytest.raises(ValueError, match="signature"):
        training.train(tmp_path, cfg, resume=True)
