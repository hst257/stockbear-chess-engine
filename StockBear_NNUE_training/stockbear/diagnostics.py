from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .common import load_config


def diagnostics(root: Path, cfg: dict) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    run = root / cfg["run"]
    metrics = load_config(run / "metrics.json")
    history = load_config(run / "history.json")
    prediction = np.load(run / "test_predictions.npy")
    teacher = np.load(run / "prepared/test_y.npy", mmap_mode="r")[:, 0]
    clipped_teacher, clipped_prediction = np.clip(teacher, -2000, 2000), np.clip(prediction, -2000, 2000)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.titleweight": "bold"})
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.4), layout="constrained")
    epochs = [row["epoch"] for row in history]
    axes[0].plot(epochs, [row["train_mse"] for row in history], color="#245e91", label="Training (epoch average)")
    axes[0].plot(epochs, [row["validation_mse"] for row in history], color="#c55a25", label="Validation")
    axes[0].axvline(metrics["best_epoch"], color="#64706d", linestyle="--", linewidth=1, label="Selected checkpoint")
    axes[0].set(xlabel="Epoch", ylabel="Blended probability MSE", title="Learning and generalization")
    axes[0].legend(frameon=False, fontsize=8)
    density = axes[1].hexbin(clipped_teacher, clipped_prediction, gridsize=45, mincnt=1, bins="log", cmap="viridis")
    figure.colorbar(density, ax=axes[1], shrink=0.75, pad=0.02, label="Positions per hexbin")
    axes[1].plot([-2000, 2000], [-2000, 2000], color="#c55a25", linewidth=1)
    axes[1].set(xlabel="Teacher score (cp, clipped)", ylabel="Network score (cp, clipped)", title="Held-out teacher agreement")
    axes[1].set_aspect("equal", adjustable="box")
    axes[2].hist(clipped_prediction - clipped_teacher, bins=60, color="#245e91", edgecolor="white", linewidth=0.4)
    axes[2].axvline(0, color="#c55a25", linewidth=1)
    axes[2].set(xlabel="Network − teacher (cp, clipped)", ylabel="Test positions", title="Held-out residuals")
    figure.suptitle(f"StockBear NNUE · {cfg['run'].split('/')[-1]} · {len(teacher):,} test positions · best epoch {metrics['best_epoch']}", fontsize=15)
    path = run / "diagnostics.png"
    figure.savefig(path, dpi=180)
    figure.savefig(run / "diagnostics.svg")
    plt.close(figure)
    return {"png": str(path), "svg": str(run / "diagnostics.svg")}
