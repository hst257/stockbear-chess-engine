"""Controlled v2 scaling extension; legacy expanded_train remains byte-for-byte intact.

Only train/validation arrays are opened. Checkpoints are epoch-atomic; a partial
epoch is replayed deterministically on resume. Never writes into legacy runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np

from .common import file_hash
from .features import FEATURE_VERSION, FEATURES, MAX_ACTIVE
from .labeling.storage import atomic_json, writer_lock

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "scaling-experiment-20261016"


def architecture(width: int, hidden: int) -> dict:
    if type(width) is not int or type(hidden) is not int or not (1 <= width <= 256 and 1 <= hidden <= 256):
        raise ValueError("Architecture dimensions must be integers between 1 and 256")
    return {"width": width, "hidden": hidden, "features": FEATURES,
            "feature_version": FEATURE_VERSION, "activation": "clip(x,0,1)",
            "output_cp_scale": 400, "parameters": (FEATURES + 2) * width + 2 * width * hidden + 2 * hidden + 1}


def load_model(state: dict):
    """Load legacy expanded or explicit new v2 checkpoints, checking all shapes."""
    from .model import NNUE
    if state.get("format", "v2") != "v2":
        raise ValueError("This experiment only accepts v2 checkpoints")
    inferred = {"width": state["model"]["bias"].numel(),
                "hidden": state["model"]["fc1.bias"].numel()}
    expected = architecture(**inferred)
    for metadata in (state.get("model_config"), state.get("architecture")):
        if metadata and any(metadata[k] != inferred[k] for k in inferred):
            raise ValueError("Architecture metadata disagrees with tensor shapes")
    config = state.get("signature", {}).get("config", {}).get("training", {})
    if any(k in config and config[k] != inferred[k] for k in inferred):
        raise ValueError("Configuration disagrees with tensor shapes")
    model = NNUE(**inferred)
    model.load_state_dict(state["model"], strict=True)
    if sum(p.numel() for p in model.parameters()) != expected["parameters"]:
        raise ValueError("Parameter count mismatch")
    return model


def verify_dataset(cfg: dict) -> tuple[Path, dict]:
    """Verify manifest identity plus ONLY development arrays; test files untouched."""
    directory = (ROOT / cfg["dataset"]).resolve()
    ready = json.loads((directory.parents[1] / "READY.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    identity = {k: v for k, v in manifest.items() if k != "fingerprint"}
    fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    if (cfg["format"] != "v2" or manifest["format"] != "v2" or fingerprint != manifest["fingerprint"]
            or fingerprint != ready["prepared"]["v2"]["fingerprint"]
            or not ready["complete"] or not ready["source_files_unchanged"]):
        raise ValueError("Expanded dataset identity/readiness mismatch")
    for split in ("train", "validation"):
        for suffix in ("x", "y", "ordinal"):
            name = f"{split}_{suffix}.npy"
            if file_hash(directory / name) != manifest["files"][name]:
                raise ValueError(f"Development array checksum mismatch: {name}")
        x = np.load(directory / f"{split}_x.npy", mmap_mode="r")
        y = np.load(directory / f"{split}_y.npy", mmap_mode="r")
        if (x.shape != (manifest["splits"][split]["positions"], 2, MAX_ACTIVE)
                or y.shape != (len(x), 8) or x.dtype != np.uint16 or y.dtype != np.float32):
            raise ValueError("Development array contract mismatch")
        x._mmap.close()
        y._mmap.close()
    return directory, manifest


def fit(cfg: dict, resume: bool = False, stop_after: int | None = None) -> dict:
    import torch
    from .model import NNUE
    from .train import atomic_checkpoint, batches, evaluate, seed_everything, target

    directory, manifest = verify_dataset(cfg)
    tc = cfg["training"]
    dimensions = architecture(tc["width"], tc["hidden"])
    run = (ROOT / cfg["run"]).resolve()
    if not run.is_relative_to((EXPERIMENT / "artifacts").resolve()):
        raise ValueError("Scaling outputs must be beneath this experiment's artifacts directory")
    if run.exists() and any(run.iterdir()) and not resume:
        raise ValueError("Run exists; use --resume with matching configuration")
    seed_everything(cfg["seed"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if tc["require_cuda"] and device != "cuda":
        raise RuntimeError("CUDA required")
    signature = {"schema": "scaling-v1", "dataset": manifest["fingerprint"], "config": cfg,
                 "architecture": dimensions, "torch": torch.__version__, "numpy": np.__version__,
                 "device": device, "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None,
                 "code_sha256": {p.relative_to(ROOT).as_posix(): file_hash(p) for p in
                                 (Path(__file__), ROOT / "stockbear/model.py", ROOT / "stockbear/train.py")}}
    model = NNUE(tc["width"], tc["hidden"]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=tc["learning_rate"],
                                 weight_decay=tc["weight_decay"], fused=device == "cuda")
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=tc["scheduler_patience"], factor=.5, min_lr=1e-5)
    data = {split: (np.load(directory / f"{split}_x.npy", mmap_mode="r"),
                    np.load(directory / f"{split}_y.npy", mmap_mode="r"))
            for split in ("train", "validation")}
    history, best, raw_best, bad, first = [], float("inf"), float("inf"), 0, 0
    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    with writer_lock(run):
        if resume:
            state = torch.load(run / "last.pt", map_location=device, weights_only=False)
            if state["signature"] != signature:
                raise ValueError("Checkpoint/config/data/runtime/source identity mismatch")
            model.load_state_dict(state["model"])
            optimizer.load_state_dict(state["optimizer"])
            scheduler.load_state_dict(state["scheduler"])
            history, best, raw_best, bad = state["history"], state["best"], state["raw_best"], state["bad"]
            first = state["epoch"] + 1
            random.setstate(state["python_rng"])
            np.random.set_state(state["numpy_rng"])
            torch.set_rng_state(state["cpu_rng"].cpu())
            if device == "cuda":
                torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda_rng"]])
        limit = min(tc["epochs"], stop_after) if stop_after is not None else tc["epochs"]
        for epoch in range(first, limit):
            if bad >= tc["patience"]:
                break
            started = time.monotonic()
            model.train()
            loss_sum, seen, last_tick = 0., 0, started
            max_gradient = 0.
            order = np.random.default_rng(cfg["seed"] + epoch).permutation(len(data["train"][1]))
            for xb, yb in batches(*data["train"], tc["batch_size"], device, order):
                optimizer.zero_grad(set_to_none=True)
                loss = (model(xb).sigmoid() - target(yb, tc["teacher_weight"])).square().mean()
                if not torch.isfinite(loss):
                    raise FloatingPointError("Nonfinite training loss")
                loss.backward()
                gradient = torch.nn.utils.clip_grad_norm_(
                    model.parameters(), tc["gradient_clip"], error_if_nonfinite=True)
                max_gradient = max(max_gradient, gradient.item())
                optimizer.step()
                loss_sum += loss.item() * len(yb)
                seen += len(yb)
                if time.monotonic() - last_tick >= 30:
                    print(json.dumps({"run": run.name, "epoch": epoch + 1, "positions": seen,
                                      "total": len(order), "seconds": time.monotonic() - started}), flush=True)
                    last_tick = time.monotonic()
            train_seconds = max(time.monotonic() - started, 1e-9)
            validation = evaluate(model, *data["validation"], tc, device)
            value = validation["blended_mse"]
            if not np.isfinite(value):
                raise FloatingPointError("Nonfinite validation loss")
            improved, raw_improved = value < best - tc["min_delta"], value < raw_best
            best, bad = (value, 0) if improved else (best, bad + 1)
            raw_best = min(raw_best, value)
            scheduler.step(value)
            row = {"epoch": epoch + 1, "train_mse": loss_sum / seen, "validation": validation,
                   "seconds": time.monotonic() - started, "train_seconds": train_seconds,
                   "training_positions_per_second": seen / train_seconds,
                   "learning_rate": optimizer.param_groups[0]["lr"], "max_gradient_norm": max_gradient,
                   "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else 0,
                   "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved() if device == "cuda" else 0,
                   "selected_checkpoint": improved, "raw_minimum_checkpoint": raw_improved}
            history.append(row)
            state = {"signature": signature, "architecture": dimensions,
                     "model_config": {"width": tc["width"], "hidden": tc["hidden"]},
                     "model": model.state_dict(), "optimizer": optimizer.state_dict(),
                     "scheduler": scheduler.state_dict(), "epoch": epoch, "best": best,
                     "raw_best": raw_best, "bad": bad, "history": history,
                     "python_rng": random.getstate(), "numpy_rng": np.random.get_state(),
                     "cpu_rng": torch.get_rng_state(), "cuda_rng": torch.cuda.get_rng_state_all() if device == "cuda" else [],
                     "format": "v2"}
            if improved:
                atomic_checkpoint(run / "best.pt", state)
            if raw_improved:
                atomic_checkpoint(run / "raw_best.pt", state)
            atomic_checkpoint(run / "last.pt", state)
            atomic_json(run / "history.json", history)
            print(json.dumps({"run": run.name, **row}), flush=True)
        if not history:
            raise ValueError("No completed epoch")
        complete = len(history) >= tc["epochs"] or bad >= tc["patience"]
        result = {"complete": complete, "architecture": dimensions, "signature": signature,
                  "epochs": len(history), "best_validation_mse": best, "raw_best_validation_mse": raw_best,
                  "seconds": sum(row["seconds"] for row in history),
                  "peak_cuda_allocated_bytes": max(row["peak_cuda_allocated_bytes"] for row in history),
                  "test_opened_or_evaluated": False}
        if complete:
            # Final and resumable checkpoints are distinct named artifacts.
            atomic_checkpoint(run / "final.pt", torch.load(run / "last.pt", map_location="cpu", weights_only=False))
            atomic_json(run / "training.json", result)
        else:
            atomic_json(run / "pilot.json", result)
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "train"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int, help="Pause at an absolute epoch boundary for pilot/resume")
    args = parser.parse_args()
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if args.action == "check":
        directory, manifest = verify_dataset(cfg)
        result = {"dataset": str(directory), "fingerprint": manifest["fingerprint"],
                  "architecture": architecture(cfg["training"]["width"], cfg["training"]["hidden"]),
                  "test_opened_or_evaluated": False}
    else:
        result = fit(cfg, args.resume, args.stop_after)
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
