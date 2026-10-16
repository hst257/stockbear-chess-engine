"""Gated, resumable single-candidate training; validation selects, test is final."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch

from ..train import seed_everything, target, atomic_checkpoint
from ..v2.learn import statistics, detailed, predict
from ..model import NNUE
from .model import KingRelativeNNUE
from .export import write_model
from .prepare import prepare, sha

TC = {"epochs": 60, "batch_size": 2048, "learning_rate": .0015,
      "weight_decay": .05, "teacher_weight": .9, "patience": 8,
      "scheduler_patience": 2, "min_delta": .00001, "gradient_clip": 1.0}
SEED = 20261016


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def load_data(root: Path, split: str, limit: int | None = None, king_buckets: int = 64):
    directory = root / "data/v3" / ("full-halfkp" if king_buckets == 64 else "bucket16")
    x = np.load(directory / f"{split}_x.npy", mmap_mode="r")
    y = np.load(directory / f"{split}_y.npy", mmap_mode="r")
    if limit:
        x, y = x[:limit], y[:limit]
    return (torch.tensor(np.asarray(x, dtype=np.int64), device="cuda"),
            torch.tensor(np.asarray(y), device="cuda"))


def fit(root: Path, pilot: bool = False, king_buckets: int = 64) -> dict:
    seed_everything(SEED)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA required for the audited experiment")
    manifest = prepare(root, king_buckets)
    suffix = "" if king_buckets == 64 else "-b"
    directory = root / "data/v3" / ("full-halfkp" if king_buckets == 64 else "bucket16")
    if not pilot:
        gates = json.loads((root / "reports/v3" / ("pilot" + suffix + ".json")).read_text())
        prototype = json.loads((root.parent / "docs/nnue-v3" / ("prototype" + suffix + "-parity.json")).read_text())
        assert gates["finite_forward_backward"] and gates["peak_cuda_bytes"] < 4.5 * 1024**3
        assert gates["estimated_full_max_epoch_seconds"] < 7200
        assert prototype["exact_feature_indices"] and prototype["max_abs_cp_error"] < .02
    name = ("pilot-" if pilot else "full-") + ("a" if king_buckets == 64 else "b")
    run = root / "runs/v3" / name
    output = root / "reports/v3" / (("pilot" if pilot else "training") + suffix + ".json")
    tc = dict(TC)
    if pilot:
        tc["epochs"] = 3
    signature = {"dataset_sha256": sha(directory / "manifest.json"), "king_buckets": king_buckets,
        "seed": SEED, "training": tc, "train_limit": 20000 if pilot else None,
        "torch": torch.__version__, "gpu": torch.cuda.get_device_name(0),
        "source_sha256": {str(p.name): sha(p) for p in Path(__file__).parent.glob("*.py")}}
    if output.exists():
        result = json.loads(output.read_text())
        if result["signature"] != signature:
            raise ValueError("Completed training signature changed")
        return result
    run.mkdir(parents=True, exist_ok=True)
    train_x, train_y = load_data(root, "train", 20000 if pilot else None, king_buckets)
    val_x, val_y = load_data(root, "validation", 2048 if pilot else None, king_buckets)
    host_y = val_y.cpu().numpy()
    model = KingRelativeNNUE(king_buckets).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=tc["learning_rate"],
                                 weight_decay=tc["weight_decay"], fused=True)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,
        patience=tc["scheduler_patience"], factor=.5, min_lr=1e-5)
    history, best, bad, first, previous_peak = [], float("inf"), 0, 0, 0
    if (run / "last.pt").exists():
        state = torch.load(run / "last.pt", map_location="cuda", weights_only=False)
        if state["signature"] != signature:
            raise ValueError("Resume configuration/data/runtime signature changed")
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        scheduler.load_state_dict(state["scheduler"])
        history, best, bad, first = state["history"], state["best"], state["bad"], state["epoch"] + 1
        torch.set_rng_state(state["cpu_rng"].cpu())
        torch.cuda.set_rng_state(state["gpu_rng"].cpu())
        previous_peak = state["peak_cuda_bytes"]
    torch.cuda.reset_peak_memory_stats()
    for epoch in range(first, tc["epochs"]):
        if bad >= tc["patience"]:
            break
        started = time.monotonic()
        model.train()
        order = torch.tensor(np.random.default_rng(SEED + epoch).permutation(len(train_y)), device="cuda")
        loss_sum = 0.0
        for start in range(0, len(order), tc["batch_size"]):
            ids = order[start:start + tc["batch_size"]]
            optimizer.zero_grad(set_to_none=True)
            loss = (model(train_x[ids]).sigmoid() - target(train_y[ids], tc["teacher_weight"])).square().mean()
            if not torch.isfinite(loss):
                raise FloatingPointError("Nonfinite v3 training loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), tc["gradient_clip"], error_if_nonfinite=True)
            optimizer.step()
            loss_sum += loss.item() * len(ids)
        prediction = predict(model, val_x)
        metrics = statistics(prediction, host_y, tc["teacher_weight"])
        value = metrics["blended_mse"]
        improved = value < best - tc["min_delta"]
        best, bad = (value, 0) if improved else (best, bad + 1)
        scheduler.step(value)
        torch.cuda.synchronize()
        row = {"epoch": epoch + 1, "train_mse": loss_sum / len(train_y),
            "validation_mse": value, "validation_teacher_mse": metrics["teacher_probability_mse"],
            "validation_cp_mae": metrics["clipped_cp_mae"], "seconds": time.monotonic() - started,
            "learning_rate": optimizer.param_groups[0]["lr"]}
        history.append(row)
        state = {"signature": signature, "model": model.state_dict(), "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(), "epoch": epoch, "best": best, "bad": bad,
            "history": history, "cpu_rng": torch.get_rng_state(), "gpu_rng": torch.cuda.get_rng_state(),
            "peak_cuda_bytes": max(previous_peak, torch.cuda.max_memory_allocated())}
        if improved:
            atomic_checkpoint(run / "best.pt", state)
        atomic_checkpoint(run / "last.pt", state)
        save(root / "reports/v3" / (name + "-history.json"), history)
        print(json.dumps({"run": name, **row}), flush=True)
    state = torch.load(run / "best.pt", map_location="cuda", weights_only=False)
    model.load_state_dict(state["model"])
    val = detailed(predict(model, val_x), host_y, tc["teacher_weight"])
    elapsed = sum(r["seconds"] for r in history)
    result = {"signature": signature, "epochs": len(history), "best_epoch": state["epoch"] + 1,
        "parameters": sum(p.numel() for p in model.parameters()), "finite_forward_backward": True,
        "peak_cuda_bytes": max(previous_peak, torch.cuda.max_memory_allocated()),
        "examples_per_second": len(train_y) * len(history) / elapsed,
        "estimated_full_max_epoch_seconds": elapsed / len(history) * manifest["splits"]["train"]["positions"] / len(train_y) * TC["epochs"],
        "validation": val, "test_evaluated": False, "history": history}
    if not pilot:
        train_prediction = predict(model, train_x)
        result["train"] = detailed(train_prediction, train_y.cpu().numpy(), tc["teacher_weight"])
        result["generalization_gap"] = val["blended_mse"] - result["train"]["blended_mse"]
        output_model = root / "exports/v3" / ("stockbear-v3-a.sbnnue" if king_buckets == 64 else "stockbear-v3-b.sbnnue")
        if output_model.exists():
            raise FileExistsError("Export exists without completed training report")
        result["export"] = write_model(output_model, model)
    save(output, result)
    return result


def final_evaluation(root: Path) -> dict:
    output = root / "reports/v3/heldout.json"
    if output.exists():
        return json.loads(output.read_text())
    seed_everything(SEED)
    contenders = {64: json.loads((root / "reports/v3/training.json").read_text())}
    if (root / "reports/v3/training-b.json").exists():
        contenders[16] = json.loads((root / "reports/v3/training-b.json").read_text())
    buckets = min(contenders, key=lambda k: contenders[k]["validation"]["blended_mse"])
    training = contenders[buckets]
    name = "full-a" if buckets == 64 else "full-b"
    save(root / "reports/v3/selection.json", {"king_buckets": buckets, "run": name,
        "criterion": "Validation blended MSE only, before test; equal-time matches remain final strength gate",
        "contenders": {str(k): v["validation"]["blended_mse"] for k, v in contenders.items()},
        "model_sha256": training["export"]["sha256"]})
    state = torch.load(root / "runs/v3" / name / "best.pt", map_location="cuda", weights_only=False)
    assert training["best_epoch"] == state["epoch"] + 1
    model = KingRelativeNNUE(buckets).cuda()
    model.load_state_dict(state["model"])
    x, y = load_data(root, "test", king_buckets=buckets)
    truth = y.cpu().numpy()
    prediction = predict(model, x)
    v2_state = torch.load(root / "runs/v2/final_compact_1250000_base/best.pt", map_location="cuda", weights_only=False)
    v2 = NNUE(32, 16).cuda()
    v2.load_state_dict(v2_state["model"])
    old_x = torch.tensor(np.asarray(np.load(root / "data/v2/prepared/1250000/test_x.npy", mmap_mode="r"), dtype=np.int64), device="cuda")
    v2_prediction = predict(v2, old_x)
    def extra(p):
        prob = 1 / (1 + np.exp(-np.clip(p / 400, -80, 80)))
        teacher = 1 / (1 + np.exp(-np.clip(truth[:, 0], -2000, 2000) / 400))
        calibration = []
        for lo in np.linspace(0, .9, 10):
            mask = (prob >= lo) & (prob < lo + .1 + (1e-7 if lo > .89 else 0))
            if mask.any():
                calibration.append({"bin": float(lo), "n": int(mask.sum()), "prediction": float(prob[mask].mean()),
                                    "teacher": float(teacher[mask].mean()), "outcome": float(truth[mask, 1].mean())})
        return {"teacher_probability_mae": float(np.abs(prob - teacher).mean()),
                "outcome_brier": float(((prob - truth[:, 1])**2).mean()), "calibration": calibration}
    result = {"selection_before_test": {"best_epoch": training["best_epoch"], "model_sha256": training["export"]["sha256"]},
        "positions": len(truth), "v3": detailed(prediction, truth, .9) | extra(prediction),
        "v2": detailed(v2_prediction, truth, .9) | extra(v2_prediction),
        "warning": "Same teacher-labeled grouped holdout; teacher accuracy does not establish chess strength."}
    np.save(root / "runs/v3" / name / "test_predictions.npy", prediction)
    save(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("pilot", "full", "evaluate"))
    parser.add_argument("--king-buckets", type=int, choices=(16, 64), default=64)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = final_evaluation(root) if args.stage == "evaluate" else fit(root, args.stage == "pilot", args.king_buckets)
    print(json.dumps({k: result[k] for k in ("epochs", "peak_cuda_bytes", "examples_per_second", "estimated_full_max_epoch_seconds") if k in result}))
