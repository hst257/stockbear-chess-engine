"""Build, gate and measure independent NNUE-only update candidates serially."""
from __future__ import annotations

import argparse

from tools.nnue_throughput import ART, ROOT, build, compare
from tools.verify_nnue_throughput import verify
from tools.analyze_nnue_throughput import summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", nargs="+", choices=("merge", "compact", "deferred", "fused", "compact-small"))
    args = parser.parse_args()
    for label in args.labels:
        flags = ["--nnue-update", label]
        build(label, flags)
        build(label, flags, micro=True)
        if not (ROOT / f"correctness-{label}.json").exists():
            verify(label, False)
        compare(label, 3, [400000])
        summarize(ROOT / f"benchmark-{label}.json")


if __name__ == "__main__":
    main()
