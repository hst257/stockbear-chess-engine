"""Measure the engine's integer White-score endpoint, including final conversion."""
import argparse
import json
from pathlib import Path
import statistics
import subprocess

from tools.audit_engine import metadata
from tools.benchmark_nnue_v2 import POSITIONS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("tools/nnue_v2_final.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--calls", type=int, default=20000)
    args = parser.parse_args()
    if args.output.exists() or min(args.repeats, args.calls) < 1:
        parser.error("Choose a fresh path and positive repeats/calls")
    configs = json.loads(args.config.read_text())
    result = {"method": "Serial rotated trials of --eval-bench; includes White POV, mate-band clamp and lround for NNUE; cached root accumulator, excludes refresh/search. Classical is uncached advanced/PST. Separate confirmation after tournaments, not a component subtraction from earlier head timings.",
              "calls_per_trial": args.calls, "repeats": args.repeats,
              "binaries": {label: metadata(Path(c["engine"])) for label,c in configs.items()}, "positions": []}
    labels = list(configs)
    for name, fen in POSITIONS.items():
        samples = {label: [] for label in labels}
        for repeat in range(args.repeats):
            for label in labels[repeat % len(labels):] + labels[:repeat % len(labels)]:
                config = configs[label]
                command = [config["engine"], "--eval-bench", "--repeats", str(args.calls)]
                if config["options"]["Evaluator"] == "nnue":
                    command.append("--nnue")
                if config.get("kernel"):
                    command += ["--kernel", config["kernel"]]
                value = json.loads(subprocess.check_output(command + [fen], text=True, timeout=60))
                assert value["calls"] == args.calls
                samples[label].append(value)
        row = {"category": name, "fen": fen, "samples": samples, "summary": {}}
        for label, values in samples.items():
            times = [v["ns_per_call"] for v in values]
            row["summary"][label] = {"median_ns": statistics.median(times), "min_ns": min(times), "max_ns": max(times),
                                      "stdev_ns": statistics.stdev(times) if len(times)>1 else 0}
        result["positions"].append(row)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Saved", args.output)


if __name__ == "__main__":
    main()
