from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import chess
import numpy as np
import torch
from torch import nn

from .common import connect, digest, file_hash, save_json
from .features import FEATURE_VERSION, MAX_ACTIVE, encode
from .model import NNUE
from .teacher import teacher_profile


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.set_num_threads(4)


def prepare(root: Path, cfg: dict) -> tuple[Path, dict]:
    directory = root / cfg["run"] / "prepared"
    profile = teacher_profile(root, cfg)
    profile_id = digest(json.dumps(profile, sort_keys=True))
    db = connect(root / cfg["cache"])
    db.execute("ATTACH DATABASE ? AS corpus", (str(root / cfg["dataset"]),))
    missing = db.execute("""SELECT count(*) FROM corpus.positions p LEFT JOIN labels l
        ON p.id=l.id AND l.profile=? WHERE l.cp IS NULL""", (profile_id,)).fetchone()[0]
    if missing:
        raise RuntimeError(f"{missing} teacher labels missing; run label first")
    directory.mkdir(parents=True, exist_ok=True)
    counts = dict(db.execute("SELECT split,count(*) FROM corpus.positions GROUP BY split"))
    if any(counts.get(split, 0) < 20 for split in ("train", "validation", "test")):
        raise ValueError("Each split needs at least 20 positions")
    content = hashlib.sha256()
    manifest = {"splits": {}, "feature_version": FEATURE_VERSION, "profile_id": profile_id}
    for split in ("train", "validation", "test"):
        size = counts[split]
        x = np.lib.format.open_memmap(directory / f"{split}_x.npy", mode="w+", dtype=np.uint16,
                                      shape=(size, 2, MAX_ACTIVE))
        # cp, result, material cp, game ply; retain unbounded cp for diagnostics.
        y = np.lib.format.open_memmap(directory / f"{split}_y.npy", mode="w+", dtype=np.float32, shape=(size, 4))
        query = """SELECT p.id,p.fen,l.cp,p.outcome,p.ply,p.game_id,p.source
            FROM corpus.positions p JOIN labels l ON p.id=l.id
            WHERE l.profile=? AND p.split=? ORDER BY p.id"""
        with (directory / f"{split}_rows.jsonl").open("w", encoding="utf-8") as rows_file:
            for i, (pid, fen, cp, outcome, ply, gid, source) in enumerate(db.execute(query, (profile_id, split))):
                board = chess.Board(fen)
                material = sum((1 if piece.color == board.turn else -1) * [0, 100, 320, 330, 500, 900, 0][piece.piece_type]
                               for piece in board.piece_map().values())
                x[i] = encode(board)
                y[i] = cp, outcome, material, ply
                line = json.dumps({"id": pid, "fen": fen, "game": gid, "source": source, "cp": cp}, sort_keys=True)
                rows_file.write(line + "\n")
                content.update((split + line + str(outcome)).encode())
        x.flush()
        y.flush()
        manifest["splits"][split] = {"positions": size, "x_sha256": file_hash(directory / f"{split}_x.npy"),
                                     "y_sha256": file_hash(directory / f"{split}_y.npy")}
    manifest["fingerprint"] = content.hexdigest()
    save_json(directory / "manifest.json", manifest)
    db.close()
    return directory, manifest


def batches(x, y, batch_size: int, device: str, indices=None):
    if indices is None:
        indices = np.arange(len(y))
    for start in range(0, len(indices), batch_size):
        ids = indices[start:start + batch_size]
        xb = torch.from_numpy(np.asarray(x[ids], dtype=np.int64))
        yb = torch.from_numpy(np.asarray(y[ids], dtype=np.float32))
        if device == "cuda":
            xb, yb = xb.pin_memory(), yb.pin_memory()
        yield xb.to(device, non_blocking=True), yb.to(device, non_blocking=True)


def target(values: torch.Tensor, teacher_weight: float) -> torch.Tensor:
    return teacher_weight * torch.sigmoid(values[:, 0].clamp(-2000, 2000) / 400) + (1 - teacher_weight) * values[:, 1]


@torch.inference_mode()
def evaluate(model, x, y, cfg, device, collect=False) -> dict:
    model.eval()
    predictions = []
    loss_sum = 0.0
    for xb, yb in batches(x, y, cfg["batch_size"], device):
        output = model(xb)
        loss_sum += ((output.sigmoid() - target(yb, cfg["teacher_weight"])) ** 2).sum().item()
        predictions.append(output.cpu().numpy() * 400)
    prediction = np.concatenate(predictions).astype(np.float64)
    teacher = np.asarray(y[:, 0], dtype=np.float64)
    teacher_prob = 1 / (1 + np.exp(-np.clip(teacher, -2000, 2000) / 400))
    predicted_prob = 1 / (1 + np.exp(-np.clip(prediction / 400, -80, 80)))
    error = np.clip(prediction, -2000, 2000) - np.clip(teacher, -2000, 2000)
    balanced = np.abs(teacher) <= 500
    decisive = np.abs(teacher) >= 100
    result = {"positions": len(y), "blended_mse": loss_sum / len(y),
              "teacher_probability_mse": float(np.mean((predicted_prob - teacher_prob) ** 2)),
              "clipped_cp_mae": float(np.mean(np.abs(error))), "clipped_cp_rmse": float(np.sqrt(np.mean(error ** 2))),
              "balanced_cp_mae": float(np.mean(np.abs(error[balanced]))) if balanced.any() else None,
              "sign_accuracy_abs_cp_ge_100": float(np.mean((prediction[decisive] > 0) == (teacher[decisive] > 0))) if decisive.any() else None,
              "prediction_cp_percentiles": np.percentile(prediction, [0, 5, 50, 95, 100]).tolist(),
              "teacher_cp_percentiles": np.percentile(teacher, [0, 5, 50, 95, 100]).tolist()}
    if collect:
        result["predictions"] = prediction
    return result


def atomic_checkpoint(path: Path, state: dict):
    temp = path.with_suffix(".tmp")
    torch.save(state, temp)
    os.replace(temp, path)


def train(root: Path, cfg: dict, resume: bool = False, stop_after: int | None = None, validation_only: bool = False) -> dict:
    start = time.monotonic()
    seed_everything(cfg["seed"])
    directory, manifest = prepare(root, cfg)
    tc = cfg["training"]
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if tc.get("require_cuda") and device != "cuda":
        raise RuntimeError("CUDA required by this configuration, but unavailable")
    data = {split: (np.load(directory / f"{split}_x.npy", mmap_mode="r"),
                    np.load(directory / f"{split}_y.npy", mmap_mode="r")) for split in ("train", "validation", "test")}
    model = NNUE(tc["width"], tc["hidden"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=tc["learning_rate"], weight_decay=tc["weight_decay"], fused=device == "cuda")
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=3, factor=0.5, min_lr=1e-5)
    run = root / cfg["run"]
    run.mkdir(parents=True, exist_ok=True)
    signature = {"dataset": manifest["fingerprint"], "seed": cfg["seed"], "profile_id": manifest["profile_id"],
                 "training": {k: v for k, v in tc.items() if k != "epochs"}, "feature_version": FEATURE_VERSION}
    first_epoch, best, bad_epochs, history = 0, float("inf"), 0, []
    last = run / "last.pt"
    if last.exists() and not resume:
        raise RuntimeError("Checkpoint exists. Pass --resume or select a new run directory")
    if resume:
        state = torch.load(last, map_location=device, weights_only=False)
        if state["signature"] != signature:
            raise ValueError("Resume signature differs: dataset, model or training parameters changed")
        if state["device"] != device or state["versions"] != {"torch": torch.__version__, "numpy": np.__version__}:
            raise ValueError("Resume runtime changed; preserve the original runtime or start a new run")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        first_epoch, best, bad_epochs, history = state["epoch"] + 1, state["best"], state["bad_epochs"], state["history"]
        random.setstate(state["random_rng"])
        np.random.set_state(state["numpy_rng"])
        torch.set_rng_state(state["torch_rng"].cpu())
        if device == "cuda":
            torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda_rng"]])
    epoch_limit = min(tc["epochs"], stop_after) if stop_after is not None else tc["epochs"]
    stopped = False
    for epoch in range(first_epoch, epoch_limit):
        if bad_epochs >= tc["patience"]:
            stopped = True
            break
        model.train()
        indices = np.random.default_rng(cfg["seed"] + epoch).permutation(len(data["train"][1]))
        loss_sum = 0.0
        seen = 0
        epoch_start = time.monotonic()
        for xb, yb in batches(*data["train"], tc["batch_size"], device, indices):
            optimizer.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = nn.functional.mse_loss(logits.sigmoid(), target(yb, tc["teacher_weight"]))
            if not torch.isfinite(loss):
                raise FloatingPointError("Nonfinite training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), tc["gradient_clip"], error_if_nonfinite=True)
            optimizer.step()
            loss_sum += loss.item() * len(yb)
            seen += len(yb)
        validation = evaluate(model, *data["validation"], tc, device)
        value = validation["blended_mse"]
        improved = value < best - tc["min_delta"]
        best, bad_epochs = (value, 0) if improved else (best, bad_epochs + 1)
        scheduler.step(value)
        row = {"epoch": epoch + 1, "train_mse": loss_sum / seen, "validation_mse": value,
               "validation_teacher_probability_mse": validation["teacher_probability_mse"],
               "validation_cp_mae": validation["clipped_cp_mae"], "lr": optimizer.param_groups[0]["lr"],
               "seconds": time.monotonic() - epoch_start}
        history.append(row)
        state = {"model": model.state_dict(), "optimizer": optimizer.state_dict(), "scheduler": scheduler.state_dict(),
                 "epoch": epoch, "best": best, "bad_epochs": bad_epochs, "history": history, "signature": signature,
                 "random_rng": random.getstate(), "numpy_rng": np.random.get_state(), "torch_rng": torch.get_rng_state(),
                 "cuda_rng": torch.cuda.get_rng_state_all() if device == "cuda" else [],
                 "model_config": {"width": tc["width"], "hidden": tc["hidden"]},
                 "versions": {"torch": torch.__version__, "numpy": np.__version__}, "device": device}
        if improved:
            atomic_checkpoint(run / "best.pt", state)
        # Publish best first. A crash here can safely replay the epoch from last;
        # publishing last first could leave it pointing at an unwritten best.
        atomic_checkpoint(last, state)
        save_json(run / "history.json", history)
        print(json.dumps(row), flush=True)
    if stop_after is not None and epoch_limit < tc["epochs"] and not stopped:
        return {"status": "interrupted_at_epoch_boundary", "completed_epochs": len(history)}
    best_state = torch.load(run / "best.pt", map_location=device, weights_only=False)
    model.load_state_dict(best_state["model"])
    evaluated_splits = ("train", "validation") if validation_only else tuple(data)
    metrics = {split: evaluate(model, *data[split], tc, device, collect=True) for split in evaluated_splits}
    teacher_train = np.asarray(data["train"][1][:, 0], dtype=np.float64)
    neutral = float(np.mean(1 / (1 + np.exp(-np.clip(teacher_train, -2000, 2000) / 400))))
    for split, result in metrics.items():
        y = data[split][1]
        teacher_prob = 1 / (1 + np.exp(-np.clip(y[:, 0].astype(np.float64), -2000, 2000) / 400))
        material_prob = 1 / (1 + np.exp(-y[:, 2].astype(np.float64) / 400))
        result["constant_baseline_teacher_probability_mse"] = float(np.mean((teacher_prob - neutral) ** 2))
        result["material_baseline_teacher_probability_mse"] = float(np.mean((teacher_prob - material_prob) ** 2))
        prediction = result.pop("predictions")
        np.save(run / f"{split}_predictions.npy", prediction)
        result["by_phase"] = {}
        for name, mask in (("early_ply_le_30", y[:, 3] <= 30), ("middle_ply_31_80", (y[:, 3] > 30) & (y[:, 3] <= 80)), ("late_ply_gt_80", y[:, 3] > 80)):
            if mask.any():
                probability = 1 / (1 + np.exp(-np.clip(prediction[mask] / 400, -80, 80)))
                result["by_phase"][name] = {"positions": int(mask.sum()), "teacher_probability_mse": float(np.mean((probability - teacher_prob[mask]) ** 2))}
        source_rows = [json.loads(line) for line in (directory / f"{split}_rows.jsonl").read_text(encoding="utf-8").splitlines()]
        if source_rows and "game" in source_rows[0]:
            games = sorted({row["game"] for row in source_rows})
            mapping = {gid: i for i, gid in enumerate(games)}
            group = np.array([mapping[row["game"]] for row in source_rows])
            squared_errors = (1 / (1 + np.exp(-np.clip(prediction / 400, -80, 80))) - teacher_prob) ** 2
            sums = np.bincount(group, weights=squared_errors, minlength=len(games))
            counts = np.bincount(group, minlength=len(games))
            rng = np.random.default_rng(cfg["seed"])
            bootstraps = []
            for _ in range(500):
                selection = rng.integers(0, len(games), len(games))
                bootstraps.append(float(sums[selection].sum() / counts[selection].sum()))
            result["games"] = len(games)
            result["game_bootstrap_teacher_mse_95_ci"] = np.percentile(bootstraps, [2.5, 97.5]).tolist()
        result["by_source"] = {}
        for source in sorted({row["source"] for row in source_rows}):
            mask = np.array([row["source"] == source for row in source_rows])
            probability = 1 / (1 + np.exp(-np.clip(prediction[mask] / 400, -80, 80)))
            result["by_source"][source] = {"positions": int(mask.sum()), "teacher_probability_mse": float(np.mean((probability - teacher_prob[mask]) ** 2))}
        worst = np.argsort(np.abs(np.clip(prediction, -2000, 2000) - np.clip(y[:, 0], -2000, 2000)))[-20:][::-1]
        save_json(run / f"{split}_worst_errors.json", [{**source_rows[i], "predicted_cp": float(prediction[i])} for i in worst])
    report = {"status": "complete", "device": device, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
              "parameters": sum(p.numel() for p in model.parameters()), "epochs": len(history),
              "best_epoch": best_state["epoch"] + 1, "early_stopping": stopped or bad_epochs >= tc["patience"],
              "seconds_this_invocation": time.monotonic() - start, "dataset_fingerprint": manifest["fingerprint"],
              "metrics": metrics, "generalization_gap": metrics["validation"]["blended_mse"] - metrics["train"]["blended_mse"],
              "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else 0,
              "validation_only": validation_only}
    save_json(run / "metrics.json", report)
    return report
