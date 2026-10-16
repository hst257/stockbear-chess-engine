"""Validation-only comparisons and isolated native benchmarks for the scaling study."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import subprocess

import numpy as np

from .common import file_hash
from .features import FEATURE_VERSION, FEATURES
from .labeling.storage import atomic_json
from .scaling_train import EXPERIMENT, ROOT, architecture, load_model, verify_dataset


def phase_metrics(prediction: np.ndarray, y: np.ndarray) -> dict:
    """Same definitions as train.evaluate; float64 aggregation for phase slices."""
    teacher = np.asarray(y[:, 0], dtype=np.float64)
    teacher_probability = 1 / (1 + np.exp(-np.clip(teacher, -2000, 2000) / 400))
    probability = 1 / (1 + np.exp(-np.clip(prediction / 400, -80, 80)))
    target = .9 * teacher_probability + .1 * y[:, 1]
    error = np.clip(prediction, -2000, 2000) - np.clip(teacher, -2000, 2000)
    balanced, decisive = np.abs(teacher) <= 500, np.abs(teacher) >= 100
    return {"positions": len(y), "blended_mse": float(np.mean((probability - target) ** 2)),
            "teacher_probability_mse": float(np.mean((probability - teacher_probability) ** 2)),
            "clipped_cp_mae": float(np.abs(error).mean()), "clipped_cp_rmse": float(np.sqrt((error ** 2).mean())),
            "balanced_cp_mae": float(np.abs(error[balanced]).mean()) if balanced.any() else None,
            "sign_accuracy_abs_cp_ge_100": float(np.mean((prediction[decisive] > 0) == (teacher[decisive] > 0))) if decisive.any() else None}


def paired_game_interval(prediction, baseline, y, repetitions=1000) -> dict:
    teacher = 1 / (1 + np.exp(-np.clip(y[:, 0].astype(np.float64), -2000, 2000) / 400))
    error = lambda p: (1 / (1 + np.exp(-np.clip(p / 400, -80, 80))) - teacher) ** 2
    difference = error(prediction) - error(baseline)
    games, group = np.unique(y[:, 7].astype(np.int64), return_inverse=True)
    sums = np.bincount(group, weights=difference)
    counts = np.bincount(group)
    rng = np.random.default_rng(20261016)
    samples = []
    for _ in range(repetitions):
        sample = rng.integers(len(games), size=len(games))
        samples.append(float(sums[sample].sum() / counts[sample].sum()))
    return {"games": len(games), "replicates": repetitions,
            "teacher_mse_difference": float(difference.mean()),
            "paired_game_bootstrap_95_percentile_interval": np.percentile(samples, [2.5, 97.5]).tolist(),
            "scope": "Validation game resampling, conditional on one trained seed; excludes training-seed uncertainty"}


def compare() -> dict:
    import torch
    from .train import evaluate, seed_everything
    seed_everything(20261016)
    cfg = json.loads((EXPERIMENT / "baseline.json").read_text(encoding="utf-8"))
    directory, manifest = verify_dataset(cfg)
    data = {split: (np.load(directory / f"{split}_x.npy", mmap_mode="r"),
                    np.load(directory / f"{split}_y.npy", mmap_mode="r"))
            for split in ("train", "validation")}
    device = "cuda" if torch.cuda.is_available() else "cpu"
    results, predictions = {}, {}
    for name in ("baseline", "medium", "large"):
        current = json.loads((EXPERIMENT / f"{name}.json").read_text(encoding="utf-8"))
        run = ROOT / current["run"]
        completion = json.loads((run / "training.json").read_text(encoding="utf-8"))
        if not completion["complete"] or completion.get("dataset", manifest["fingerprint"]) != manifest["fingerprint"]:
            raise ValueError("Training incomplete or dataset mismatch")
        checkpoint = run / "best.pt"
        state = torch.load(checkpoint, map_location="cpu", weights_only=False)
        if state["signature"]["dataset"] != manifest["fingerprint"]:
            raise ValueError("Checkpoint dataset mismatch")
        model = load_model(state).to(device)
        validation = evaluate(model, *data["validation"], cfg["training"], device, collect=True)
        prediction = validation.pop("predictions")
        predictions[name] = prediction
        np.save(EXPERIMENT / "artifacts" / f"{name}-validation-predictions.npy", prediction)
        if abs(validation["blended_mse"] - state["history"][-1]["validation"]["blended_mse"]) > 1e-7:
            raise ValueError("Reloaded checkpoint does not reproduce its saved validation loss")
        train_metrics = evaluate(model, *data["train"], cfg["training"], device)
        history = json.loads((run / "history.json").read_text(encoding="utf-8"))
        raw_minimum = min(history, key=lambda row: row["validation"]["blended_mse"])
        result = {"architecture": architecture(model.width, model.hidden), "checkpoint": str(checkpoint.resolve()),
                  "sha256": file_hash(checkpoint), "best_epoch": state["epoch"] + 1, "completed_epochs": len(history),
                  "training_seconds": sum(row["seconds"] for row in history), "config": current,
                  "training_complete": completion, "validation": validation, "selected_training_metrics": train_metrics,
                  "generalization_gap": validation["blended_mse"] - train_metrics["blended_mse"],
                  "raw_minimum_history_epoch": raw_minimum["epoch"],
                  "raw_minimum_history_mse": raw_minimum["validation"]["blended_mse"],
                  "history": history, "by_phase": {}}
        for index, phase in enumerate(("opening", "middlegame", "endgame")):
            mask = data["validation"][1][:, 4] == index
            if mask.any():
                result["by_phase"][phase] = phase_metrics(prediction[mask], data["validation"][1][mask])
        result["auxiliary_checkpoints"] = {}
        for filename in ("last.pt", "raw_best.pt"):
            path = run / filename
            if path.exists():
                auxiliary = torch.load(path, map_location="cpu", weights_only=False)
                aux_model = load_model(auxiliary).to(device)
                result["auxiliary_checkpoints"][filename] = {
                    "path": str(path.resolve()), "sha256": file_hash(path), "epoch": auxiliary["epoch"] + 1,
                    "validation": evaluate(aux_model, *data["validation"], cfg["training"], device)}
        results[name] = result
        print(json.dumps({"model": name, "validation": validation, "best_epoch": result["best_epoch"]}), flush=True)
    for name in ("medium", "large"):
        results[name]["differences_vs_baseline"] = {
            metric: {"absolute": value - results["baseline"]["validation"][metric],
                     "percent": 100 * (value / results["baseline"]["validation"][metric] - 1)}
            for metric, value in results[name]["validation"].items()
            if type(value) in (int, float) and metric != "positions"}
        results[name]["paired_uncertainty"] = paired_game_interval(
            predictions[name], predictions["baseline"], data["validation"][1])
    report = {"dataset_fingerprint": manifest["fingerprint"], "validation_positions": len(data["validation"][1]),
              "seed": 20261016, "test_opened_or_evaluated": False, "models": results}
    atomic_json(EXPERIMENT / "comparison.json", report)
    return report


def export_checkpoint(checkpoint: Path, destination: Path) -> dict:
    """Generic float32 export without the legacy export command's test-data reads."""
    import torch
    from .export import load_export
    state = torch.load(checkpoint, map_location="cpu", weights_only=False)
    model = load_model(state)
    tensors, payload = [], bytearray()
    for name, tensor in model.state_dict().items():
        array = np.ascontiguousarray(tensor.numpy(), dtype="<f4")
        if not np.isfinite(array).all():
            raise ValueError("Nonfinite export weights")
        tensors.append({"name": name, "shape": list(array.shape), "dtype": "<f4", "offset": len(payload)})
        payload.extend(array.tobytes())
    header = {"format": "StockBear float32 v1", "feature_version": FEATURE_VERSION, "features": FEATURES,
              "model": {"width": model.width, "hidden": model.hidden}, "score_pov": "side_to_move",
              "output_cp_scale": 400, "activation": "clip(x,0,1)", "tensors": tensors,
              "payload_sha256": hashlib.sha256(payload).hexdigest(), "best_epoch": state["epoch"] + 1,
              "source_checkpoint_sha256": file_hash(checkpoint), "experiment": EXPERIMENT.name}
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    content = b"SBNNUE1\0" + struct.pack("<I", len(encoded)) + encoded + payload
    if not destination.resolve().is_relative_to((EXPERIMENT / "artifacts").resolve()):
        raise ValueError("Exports must stay inside experiment artifacts")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != content:
        raise ValueError("Refusing to overwrite a different existing export")
    destination.write_bytes(content)
    load_export(destination)
    return header


def validation_fens(directory: Path, count=128) -> list[dict]:
    ordinals = np.load(directory / "validation_ordinal.npy", mmap_mode="r")
    selection = np.random.default_rng(20261016).choice(len(ordinals), count, replace=False)
    with sqlite3.connect((directory.parents[1] / "merged.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        rows = []
        for index in selection:
            ordinal = int(ordinals[index])
            row = db.execute("SELECT fen,split FROM records WHERE ordinal=?", (ordinal,)).fetchone()
            if row is None or row[1] != "validation":
                raise ValueError("Golden position is outside validation")
            rows.append({"ordinal": ordinal, "validation_index": int(index), "fen": row[0]})
    return rows


def native(build_only=False) -> dict:
    """Compile unchanged production inference into separate development binaries."""
    import torch
    from .features import encode
    import chess
    cfg = json.loads((EXPERIMENT / "baseline.json").read_text(encoding="utf-8"))
    directory, _ = verify_dataset(cfg)
    rows = validation_fens(directory)
    atomic_json(EXPERIMENT / "validation-goldens.json", rows)
    repo = ROOT.parent
    builder_python = repo / ".venv/Scripts/python.exe"
    all_results = {}
    for name in ("baseline", "medium", "large"):
        cfg = json.loads((EXPERIMENT / f"{name}.json").read_text(encoding="utf-8"))
        destination = EXPERIMENT / "artifacts/native" / name
        checkpoint = ROOT / cfg["run"] / "best.pt"
        exported = destination / f"{name}.sbnnue"
        export_checkpoint(checkpoint, exported)
        binary = destination / "micro.exe"
        command = [str(builder_python), str(repo / "tools/build_engine.py"), "--target", "nnue-bench",
                   "--nnue-model", str(exported), "--output", str(binary), "--optimization", "O2"]
        build = subprocess.run(command, cwd=repo, text=True, capture_output=True)
        (destination / "build.log").write_text(build.stdout + build.stderr, encoding="utf-8")
        if build.returncode:
            raise RuntimeError(f"Isolated build failed; see {destination / 'build.log'}")
        if build_only:
            continue
        model = load_model(torch.load(checkpoint, map_location="cpu", weights_only=False)).eval()
        with torch.inference_mode():
            expected = model(torch.from_numpy(np.stack([encode(chess.Board(row["fen"])) for row in rows]))).numpy() * 400
        results = {"export": str(exported), "export_sha256": file_hash(exported),
                   "build_command": command, "build": json.loads(binary.with_suffix(".build.json").read_text(encoding="utf-8")),
                   "cpu": json.loads(subprocess.check_output([str(binary), "--cpu"], text=True)), "kernels": {}}
        for kernel in ("scalar", "quant"):
            verified = json.loads(subprocess.check_output([str(binary), "--verify", kernel], text=True))
            compact = json.loads(subprocess.check_output([str(binary), "--verify-throughput", kernel], text=True))
            actual = np.fromstring(subprocess.check_output([str(binary), "--batch", kernel],
                                   input="\n".join(row["fen"] for row in rows) + "\n", text=True), sep="\n")
            if actual.shape != expected.shape:
                raise AssertionError("Native parity output count mismatch")
            error = np.abs(actual - expected)
            tolerance = .01 if kernel == "scalar" else 5.
            if error.max() > tolerance:
                raise AssertionError(f"Native {kernel} parity failed: {error.max()} cp")
            samples = []
            # Same 12 validation positions, five repeats. Hot per-position loops.
            for repeat in range(5):
                for index, row in enumerate(rows[:12]):
                    measurement = json.loads(subprocess.check_output(
                        [str(binary), row["fen"], "20000", kernel], text=True))
                    samples.append({"repeat": repeat, "position": index, **measurement})
            results["kernels"][kernel] = {"accumulator_verification": verified, "compact_update_verification": compact,
                "validation_golden_positions": len(rows), "max_cp_error_vs_torch": float(error.max()),
                "mean_cp_error_vs_torch": float(error.mean()), "samples": samples,
                "median_ns": {metric: float(np.median([s[metric] for s in samples])) for metric in
                              ("feature_ns", "copy_ns", "update_ns", "move_update_ns", "refresh_ns", "head_ns")}}
        all_results[name] = results
        atomic_json(EXPERIMENT / "native-benchmark.json", all_results)
        print(json.dumps({"model": name, "kernels": {k: v["median_ns"] for k, v in results["kernels"].items()}}), flush=True)
    return all_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("compare", "native"))
    args = parser.parse_args()
    if args.action == "compare":
        compare()
    else:
        native()


if __name__ == "__main__":
    main()
