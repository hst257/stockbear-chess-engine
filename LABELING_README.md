# Standalone Stockfish labeling

Run from the repository root in PowerShell. This tool reads
`StockBear_NNUE_training/data/raw/new_data`, including its downloaded plain PGNs.
It also supports `.pgn.gz`, `.pgn.bz2`, `.pgn.xz`, `.pgn.zst` and PGNs inside ZIPs,
without unpacking archives to disk. It never starts NNUE training or changes the
original corpus, models or engine. No Codex session is needed while it runs.

## Dependencies

The existing training environment already contains the required packages. If an
environment is missing, create a separate lightweight one (no CUDA/PyTorch):

```powershell
Set-Location 'Z:\Code\Chess'
py -3.11 -m venv .\StockBear_NNUE_training\.venv-labeling
.\StockBear_NNUE_training\.venv-labeling\Scripts\python.exe -m pip install -r .\StockBear_NNUE_training\requirements-labeling.txt
```

The launcher prefers the existing training `.venv`; use `-Python` to select
another interpreter. These commands bypass script policy only for the child
PowerShell process, without changing system policy.

## Test, start and resume

```powershell
# Separate bounded test: ingestion, deduplication, at most 100 labels, validation/export.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -DryRun -Limit 100 -OutputDirectory .\StockBear_NNUE_training\data\labeling\smoke-100

# Full labeling: start this yourself when ready. Default output: data/labeling/gm-extra-v1.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1

# Ctrl+C stops safely. After interruption/reboot, restart with the same output:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Resume
```

`--limit`/`-Limit` bounds the **total selected queue**, not labels per restart.
The dry-run configuration stays bounded on resume. Use a separate output for the
full run. Completed labels commit individually; an interrupted analysis may be
repeated, but committed records are never duplicated. PGN ingestion checkpoints
each game and reparses compressed input to its saved cursor when resuming.

Live progress shows completed/remaining positions, measured positions/second,
elapsed time and approximate ETA. ETA starts after successful labels arrive.
After the last label, source/corpus fingerprint checks and export continue until
the command exits; large existing databases can make this final step take minutes.
Keep the computer awake for unattended operation; after sleep/restart, resume.

## Configuration

For a large **already ingested/planned** queue, use the compatible fast runner:

```powershell
# Check fingerprints and queue readiness only; starts no Stockfish workers.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Resume -FastResume -ExecutionWorkers 4 -CheckResume -OutputDirectory .\StockBear_NNUE_training\data\labeling\cc-events-v1

# Actually resume the existing queue when ready:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Resume -FastResume -ExecutionWorkers 4 -OutputDirectory .\StockBear_NNUE_training\data\labeling\cc-events-v1
```

This leaves the original signed pipeline modules, saved configuration, teacher
profile, ingestion and queue unchanged. It fetches bounded batches through the
ordinal index, retries failed work locally, and derives live progress from
committed results rather than scanning millions of labels every update. A restart
derives counters from SQL again and skips completed rows. FULL-synchronous,
per-result commits remain enabled. `fast-runtime.json` identifies the separate
runner and actual concurrency. `-ExecutionWorkers` is an execution override;
`-Workers`, nodes, threads, hash and sampling stay part of the frozen configuration.
The legacy resume path remains available. Fast resume refuses an incomplete
ingestion or unplanned queue, and never rebuilds either.

To try eight single-thread workers, use the same command with
`-ExecutionWorkers 8`. An explicit override may use up to the reported logical
CPU count, capped at eight workers and 4096 MiB total hash; the default remains
conservative. Stop the old run with Ctrl+C before switching worker counts.
The i5-13420H's bounded 48-position comparison measured 109.9/s with four workers
and 136.5/s with eight (+24.3%), with identical labels. This short warm test does
not establish sustained throughput or thermal behavior; use live ETA to judge.
[Raw results and preservation checks](docs/labeling-workers-20261016.json).

See the [measured throughput diagnosis](LABELING_THROUGHPUT_DIAGNOSIS.md) for
the multi-million-row query bottleneck, preservation proof and bounded worker
comparison. Its short-batch ETA is an estimate; live progress measures the actual run.
That report's source manifest records the original fix at commit `76c539d`;
the explicit eight-worker extension is identified as runtime version 2.

Paths are discovered relative to the script, rather than this machine's username
or drive letter. Defaults: local Stockfish, **16,384 nodes, 2 workers × 1 thread,
64 MiB hash per worker**, seed 20261015, 16 sampled positions/game, plies 16–240,
four-ply spacing. Example with custom paths:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -InputDirectory 'Z:\datasets\games' -OutputDirectory 'Z:\datasets\labels-gm-2026' -Stockfish 'Z:\tools\stockfish.exe' -Workers 2 -Threads 1 -HashMB 64 -Nodes 16384
```

Use the same `-OutputDirectory` with `-Resume`; saved settings are restored.
Changed inputs, corpus hashes, executable, configuration, dependencies or pipeline
code are rejected. Keep this revision for an existing run. More downloads or a
different budget require a fresh output directory. CPU concurrency is capped at
half the logical CPUs and eight workers; the default uses only two. Multiple
threads can make teacher searches nondeterministic. `-Encoding cp1252` supports
non-UTF-8 PGNs; decoding errors are recorded rather than silently replacing text.

## Progress, validation and errors

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Mode status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Mode validate
# Only after inspecting persistent teacher failures; prior errors are retained:
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Resume -RetryFailed
```

Output contains `pipeline.sqlite`, `config.json`, periodic `progress.json` and
`progress.log`, plus final `validation.json`, `manifest.json` and `export/`.
The database is authoritative after a crash; summary files can lag by one progress
interval. Errors/skipped games are stored transactionally and exported to
`export/errors.jsonl`. Exit code 0 means success, 130 means interrupted, 1 means
inspect the error. Failed labels are never valid records. Automatic retries are
bounded to three; ten consecutive teacher errors stop new work. One writer may
own an output directory; `status` works while it runs. All outputs stay on a
non-system drive. Do not copy only the SQLite file while it is running: its WAL
contains recent commits. Stop first, or keep the entire output directory together.

## Label compatibility and leakage controls

FENs use legal en passant and normalized `0 1` counters. Position IDs are SHA256
of those FENs. Fresh Stockfish state, side-to-move centipawns, signed mate distance,
±2000 cp mate labels and side-to-move game outcomes match v2/v3. Nonmate cp stays
unclipped in storage. Training target: `0.9 * sigmoid(clip(cp,-2000,2000)/400)
+ 0.1 * outcome`. Teacher version, executable hash, options, actual nodes/depth,
source headers, source-game IDs and all sampled occurrences remain recorded.

Existing v1/v2 position databases are attached read-only; exact duplicate FENs
are excluded before labeling. New repeated boards and conflicting game outcomes
are excluded/deduplicated. Deterministic phase-balanced sampling caps each game.
Families join legacy header identity, full move hashes, same-player/day/prefix
aliases and repeated uncommon late-position overlaps. Frozen game anchors retain
their original partitions; conflicting anchors quarantine the family. Remaining
families use the existing seeded 80/10/10 hash split. These conservative checks
cover identifiable duplicates, not arbitrary semantic similarity. Sampling and
quarantine counts are reported explicitly.

Contradictory header/movetext results are skipped. For later batches, completed
`pipeline.sqlite` files can also be supplied as existing corpora; their game
aliases and frozen partitions are retained. `-ExistingCorpus` replaces the
default corpus list, so include the original `data/processed/full.sqlite` and
`data/v2/pool.sqlite` alongside any additional corpus. The Python CLI supports
repeated `--existing-corpus PATH` arguments for this purpose.

## Export and prepare future training data

The full run automatically validates every FEN/label, checks original-corpus
overlap and family partitions, and exports checksummed JSONL with normalized
provenance. These commands can repeat verification/export without Stockfish:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Mode export
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Mode prepare -Features v2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_labeling.ps1 -Mode prepare -Features v3-bucket16
# Use -Features v3-full for 64-square king conditioning.
```

Prepared files under `prepared/<features>/` preserve existing `*_x.npy`,
`*_y.npy` (eight columns) and `*_ordinal.npy` contracts. `game_ids.json` maps local
numeric indices to stable family IDs; unknown years are 0. Before combining with
old arrays, remap game IDs jointly and honor frozen splits; blindly concatenating
local group numbers is unsafe. Existing trainers intentionally retain their
frozen dataset paths. This step prepares new compatible arrays and does not
modify those paths, merge datasets or train a model. Empty tiny-test splits are
allowed and reported; a future training dataset needs adequate holdouts.

The separate [expanded-corpus preparation workflow](EXPANDED_TRAINING_README.md)
verifies a completed run, merges compatible original and expanded labels with
joint game IDs, and prepares all three feature formats in a new directory.
It includes explicit training configurations without replacing frozen experiments.
