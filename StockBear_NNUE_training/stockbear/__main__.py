from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")


def main():
    parser = argparse.ArgumentParser(description="Standalone StockBear NNUE pipeline")
    parser.add_argument("command", choices=("audit", "sample", "label", "validate", "train", "export", "diagnostics", "run"))
    parser.add_argument("--config", default="configs/pilot.json")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--limit", type=int, help="Bound the number of new labels; next label invocation resumes")
    parser.add_argument("--stop-after", type=int, help="Stop training at this epoch boundary to exercise recovery")
    parser.add_argument("--validation-only", action="store_true", help="Report train/validation only while selecting an experiment")
    args = parser.parse_args()
    from .common import load_config
    root = args.root.resolve()
    cfg_path = Path(args.config)
    cfg = load_config(cfg_path if cfg_path.is_absolute() else root / cfg_path)
    from .sample import sample
    from .teacher import label
    if args.command in ("audit", "run"):
        from .audit import audit
    if args.command in ("train", "run"):
        from .train import train
    if args.command in ("export", "run"):
        from .export import export
    if args.command == "run":
        audit(root, cfg)
        sample(root, cfg)
        labeling = label(root, cfg)
        if labeling["remaining"]:
            raise RuntimeError("Labeling incomplete; inspect failures before training")
        from .validate import validate
        validate(root, cfg)
        training = train(root, cfg, resume=args.resume)
        result = {"training": training, "export": export(root, cfg)}
    elif args.command == "train":
        result = train(root, cfg, resume=args.resume, stop_after=args.stop_after, validation_only=args.validation_only)
    elif args.command == "label":
        result = label(root, cfg, limit=args.limit)
    elif args.command == "audit":
        result = audit(root, cfg)
    elif args.command == "sample":
        result = sample(root, cfg)
    elif args.command == "validate":
        from .validate import validate
        result = validate(root, cfg)
    elif args.command == "diagnostics":
        from .diagnostics import diagnostics
        result = diagnostics(root, cfg)
    else:
        result = export(root, cfg)
    print(json.dumps(result, indent=2, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
