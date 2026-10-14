"""Measure evaluator CPU cost separately from search-tree changes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import subprocess

from app.engine_client import DEFAULT_ENGINE
from tools.benchmark_optimizations import POSITIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--repeats", type=int, default=100000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ablation", action="store_true")
    args = parser.parse_args()
    variants = {"baseline": ["--baseline"], "advanced": []}
    if args.ablation:
        for name in ("Pawns", "Passers", "BishopPair", "Rooks", "Mobility", "Outposts", "KingSafety", "Space", "Endgame"):
            variants["without_" + name] = ["--disable", "Eval" + name]
    rows = []
    for name in ("opening", "middlegame", "endgame"):
        for variant, flags in variants.items():
            samples = [json.loads(subprocess.check_output(
                [str(DEFAULT_ENGINE), "--eval-bench", "--repeats", str(args.repeats), *flags, POSITIONS[name]],
                text=True, timeout=30)) for _ in range(3)]
            rows.append({"position": name, "variant": variant,
                         "ns_per_call": statistics.median(s["ns_per_call"] for s in samples), "samples": samples})
    path = args.output or Path(f"docs/evaluation-stages/{args.stage}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"stage": args.stage, "platform": platform.platform(),
                               "engine_sha256": hashlib.sha256(DEFAULT_ENGINE.read_bytes()).hexdigest(),
                               "measurements": rows}, indent=2) + "\n", encoding="utf-8")
    print("; ".join(f"{r['position']}/{r['variant']}: {r['ns_per_call']:.0f} ns" for r in rows), flush=True)


if __name__ == "__main__":
    main()
