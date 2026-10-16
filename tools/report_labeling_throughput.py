"""Publish the bounded investigation and immutable-live-state evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parents[1]
ART=ROOT/"artifacts/labeling/performance-20261016"
DOC=ROOT/"docs/labeling-performance"


def read(name: str) -> dict:
    return json.loads((ART/name).read_text(encoding="utf-8-sig"))


def main() -> None:
    baseline,native=read("baseline.json"),read("native.json")
    replay,preserved=read("database-replay-final.json"),read("preservation.json")
    comparison,keysets=read("workload-comparison.json"),read("keyset-batches.json")
    preflight=read("preflight.json")
    assert preserved["byte_identical"] and preflight["safe_to_resume"] and not preflight["workers_started"]
    assert native["native_analyses"]==96 and native["two_four_exact_labels"]
    assert comparison["smoke-100"]["profile"]==comparison["cc-events-v1"]["profile"]
    DOC.mkdir(exist_ok=True)
    sources=("baseline.json","native.json","database-replay-final.json","workload-comparison.json",
             "preservation.json","preflight.json","keyset-batches.json","live-database-before.json")
    for name in sources:
        (DOC/name).write_text(json.dumps(read(name),indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    two,four=native["worker_trials"]
    old=baseline["counts"]["pending"]
    oldrate=comparison["cc-events-v1"]["observed_progress"]["positions_per_second"]
    point={str(r["workers"]):old/r["result"]["positions_per_second"]/3600 for r in replay["trials"]}
    commits=replay["commit_probe"]
    report=f'''# StockBear labeling throughput diagnosis

## Finding

The slowdown is **SQLite work scheduling**, not a larger Stockfish search budget.
The stopped run retains **4,470,665 queued positions, 351 completed labels and
4,470,314 pending positions**, with no exhausted teacher failures.

The old pending query scans all labels, looks up each position and builds a
temporary sorting B-tree, even when requesting only four rows. It takes
**{min(baseline['queries']['queue']['seconds']):.2f}–{max(baseline['queries']['queue']['seconds']):.2f} seconds per request**.
It runs again in the worker-dispatch loop, leaving completed Stockfish workers
idle while Python waits for the next database result. Progress reporting adds
another **{baseline['counts_seconds']:.2f}-second whole-table scan** each update.

The same slow query takes {comparison['no_lock_wait_probe']['query_seconds']:.2f}s
with SQLite busy waiting disabled and raises no lock error. This reproduces the
problem without another writer: lock contention is not the explanation.

## Measurements

| Operation | Measured time |
| --- | ---: |
| Original full-queue selection, four rows | 4.45–4.58 s |
| Original complete progress counts | {baseline['counts_seconds']*1000:.1f} ms |
| Indexed keyset selection, 64 rows near current progress | {keysets[0]['median_seconds']*1000:.3f} ms median |
| Indexed keyset selection, 64 rows halfway/end | {keysets[1]['median_seconds']*1000:.3f}/{keysets[2]['median_seconds']*1000:.3f} ms median |
| FULL/WAL commit in disposable database, 1,024 writes | {commits['mean_commit_seconds']*1000:.3f} ms mean, {commits['p99_commit_seconds']*1000:.3f} ms p99 |
| Stockfish worker call, two workers | {two['mean_service_seconds']*1000:.2f} ms mean |
| Stockfish worker call, four workers | {four['mean_service_seconds']*1000:.2f} ms mean |
| Stockfish-reported search time, two/four workers | {two['mean_engine_seconds']*1000:.2f}/{four['mean_engine_seconds']*1000:.2f} ms mean |

Stockfish worker-call timing includes FEN validation, UCI communication and the
required clean-game/hash reset; engine-reported search time does not cover all
of that overhead. The SQLite write probe includes periodic WAL checkpoints but
uses a small scratch B-tree, so it is not a direct latency measurement of writes
to the 9GB live database. FULL synchronization was preserved; it was not relaxed.

## Smoke versus full run

Both use the exact same teacher profile
`{comparison['cc-events-v1']['profile_id']}`: Stockfish 19, 16,384 nodes,
two independent workers, one thread each, Hash64 per worker, cleared state,
side-to-move scores, and the original mate/target conventions.

| Persisted workload | Smoke | Full run |
| --- | ---: | ---: |
| Queue size | 100 | 4,470,665 |
| Completed labels inspected | 100 | 351 |
| Mean actual nodes | {comparison['smoke-100']['mean_actual_nodes']:.2f} | {comparison['cc-events-v1']['mean_actual_nodes']:.2f} |
| Actual node range | 16,384–16,407 | 16,384–16,426 |
| Opening/middlegame/endgame labels | 14/60/26 | 23/221/107 |

The smoke queue contains recent GM games; the full queue includes historical
games. Those differences cannot explain seconds spent in the pending SQL query.
The smoke run is also short and includes worker startup; it is not a warmed,
sustained throughput baseline. Small node overshoots are normal and nearly
identical across workloads. No completed position was reanalyzed.

The old rate calculation is correct: 351 new labels / 1,822.125 seconds =
**{oldrate:.5f} positions/s**, implying {old/oldrate/86400:.1f} days at that broken
dispatch rate. The clock was measuring real database-induced idleness, not
reporting a units error.

## Bounded two-versus-four-worker experiment

Selected 48 existing pending FENs: 12 near the current queue head and 36 spread
through the remaining ordinal range. Each was analyzed once with two workers
and once with four, **96 total analyses**. Engines were initialized before timing.
The live labels and attempt counts were never updated.

| Workers × threads | Warm native positions/s | Shadow replay positions/s | Labeling-only projection |
| --- | ---: | ---: | ---: |
| 2 × 1 | {two['positions_per_second']:.2f} | {replay['trials'][0]['result']['positions_per_second']:.2f} | {point['2']:.1f} h |
| 4 × 1 | {four['positions_per_second']:.2f} | {replay['trials'][1]['result']['positions_per_second']:.2f} | {point['4']:.1f} h |

All 48 score/mate/depth/node tuples match exactly between worker counts. Mean
actual nodes are {two['mean_actual_nodes']:.3f}. Four workers improved this short
native batch by {(native['four_two_throughput_ratio']-1)*100:.1f}%, despite slower
individual calls under CPU contention. Four single-thread workers fit the
i5-13420H's conservative existing concurrency cap and use 256MiB total teacher hash.

Shadow replay sleeps for measured native service times and commits cached
results through the finalized scheduler in separate 48-row databases. It starts
no additional Stockfish searches. Its rates are a composed estimate, not measured
sustained live-run throughput. Native batches lasted less than one second;
turbo, power settings, thermal throttling, background load and larger write trees
limit extrapolation. No affinity or power settings were changed.

**A practical working estimate is roughly 12–24 hours for labeling with four
workers**, based on the {point['4']:.1f}h warmed projection with operating margin;
this is not a confidence interval or a completion guarantee. Final full-dataset
validation/export is additional. The resumed process will replace that estimate
with committed-label throughput over real elapsed time as the run continues.

## Compatible fix and preservation

`stockbear.labeling_runtime` is a separately identified adapter. The original
signed `stockbear/labeling/*.py` modules are byte-for-byte unchanged, so existing
source, input, dependency, configuration and teacher fingerprint checks remain
active. There is no fingerprint bypass or replacement of the saved signature.

- Read pending batches through the ordinal index and indexed `(profile,id)`
  lookups, using an in-memory keyset cursor and bounded retry buffer.
- After restart, start the scan from zero and exclude committed/failed rows in
  SQL. There is no persisted cursor that could skip an uncommitted buffered job.
- Retry eligible failures locally behind the scan cursor; preserve bounded
  attempts, interruption behavior and one FULL-synchronous commit per result.
- Derive periodic progress from committed changes, with authoritative SQL counts
  at startup and final reconciliation. No whole-table scans per progress update.
- Refuse fast mode unless ingestion and planning are already complete. Its hooks
  verify those stages and never parse input games or rebuild the queue.
- Keep saved `workers=2` unchanged. `-ExecutionWorkers 4` is a separate scheduling
  override, retaining one thread, nodes and hash per Stockfish process. A runtime
  receipt records the new scheduler source and actual concurrency.

The entire **9,091,530,752-byte live SQLite database is byte-identical** before
and after investigation: SHA256 `{preserved['after_sha256']}`. All 351 completed
rows, pending attempt counts, original configuration and saved signature remain
unchanged. There were 22,253 ingestion skips plus the recorded Ctrl+C, not 22,254
Stockfish failures. No live index migration or schema/queue rewrite was needed.

**27 pipeline tests passed**, including legacy/fast hard-kill recovery, Ctrl+C,
retries behind the keyset cursor, sparse ordinals, manual failed-row retry,
configuration preservation and avoiding periodic aggregate scans. A check-only
PowerShell preflight passed against the actual run without starting workers.

## Exact safe resume command

From `Z:\\Code\\Chess`, run this yourself when ready:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\start_labeling.ps1 `
  -Resume -FastResume -ExecutionWorkers 4 `
  -OutputDirectory .\\StockBear_NNUE_training\\data\\labeling\\cc-events-v1
```

Add `-CheckResume` for another read-only preflight. Do not add `-DryRun`, `-Limit`,
`-RetryFailed`, or change the input/configuration for this normal continuation.
The full labeling run was **not started** during this investigation.

[Raw query plans/timings](docs/labeling-performance/baseline.json) ·
[Bounded native results](docs/labeling-performance/native.json) ·
[Scratch write/replay measurements](docs/labeling-performance/database-replay-final.json) ·
[Workload comparison](docs/labeling-performance/workload-comparison.json) ·
[Preservation proof](docs/labeling-performance/preservation.json) ·
[Resume preflight](docs/labeling-performance/preflight.json).
'''
    path=ROOT/"LABELING_THROUGHPUT_DIAGNOSIS.md"
    path.write_text(report,encoding="utf-8",newline="\n")
    files=[*DOC.glob("*.json"),path]
    files=[p for p in files if p.name!="manifest.json"]
    manifest={"files":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        "source_lf_sha256":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            for p in (ROOT/"StockBear_NNUE_training/stockbear/labeling_runtime.py",ROOT/"start_labeling.ps1",
                      ROOT/"tools/diagnose_labeling_throughput.py",ROOT/"tools/replay_labeling_database.py",Path(__file__))}}
    (DOC/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
    print("Wrote",path)


if __name__=="__main__":main()
