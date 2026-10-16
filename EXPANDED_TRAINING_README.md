# Expanded StockBear training data

The completed CC events labels are combined with all compatible labeled v1/v2
positions in a **new** corpus:
`StockBear_NNUE_training/data/expanded/cc-events-20261016/`.
Original databases, labels, prepared experiments, models and engine stay intact.
Preparation does not start Stockfish or train a network.

## Verification and merge

Preparation requires a stopped run with all positions successfully labeled. It
checks original source signatures, database integrity/foreign keys, all label and
result metadata, family partitions and frozen-corpus disjointness, then verifies
every new FEN in parallel. Existing completed JSONL exports are checksummed when
available; the authoritative SQLite labels can be used directly when automatic
post-processing has not finished. Compatible labels retain the same teacher
profile, side-to-move centipawns, mate handling and outcome perspective.

Whole-game aliases and frozen anchors share a global game index. Conflicting
family partitions are quarantined. Duplicate FENs appear once; conflicting
outcome, split or teacher-score records are excluded from the derived corpus and
recorded in `merged.sqlite`. Source records are never deleted or reassigned.

```powershell
Set-Location 'Z:\Code\Chess\StockBear_NNUE_training'
.\.venv\Scripts\python.exe -u -m stockbear.expanded_data --workers 4
# Reuse completed, verified preparation stages after interruption:
.\.venv\Scripts\python.exe -u -m stockbear.expanded_data --workers 4 --resume
```

`READY.json` is published only after source-preservation, unique-position,
family-split, array-shape, target and independent feature checks pass.
`source-audit.json`, `merge-report.json` and each feature manifest record counts,
exclusions, provenance and checksums. Incomplete SQL merges are retained and
require a new output directory; they are never declared ready.
A completed merge interrupted during checkpoint publication can resume without
copying records again. The known checkpoint-only compatibility fix preserves
its saved signature and records both code versions in `preparation-runtime.json`.

## Prepared formats

`prepared/v2`, `prepared/v3-bucket16` and `prepared/v3-full` contain separate
train/validation/test `*_x.npy`, `*_y.npy`, `*_ordinal.npy` arrays and
`game_ids.json`. Targets preserve all eight existing v2/v3 metadata columns.
V3 has either 16 king buckets or full 64-square conditioning. All formats use
identical records, targets and splits; raw centipawns remain unclipped.

## Training when explicitly requested

The new loader streams batches from memory-mapped arrays, so it does not place
the entire expanded corpus on the GPU. Existing experiment entry points remain
frozen on their old datasets. Check any new configuration without training:

```powershell
.\.venv\Scripts\python.exe -m stockbear.expanded_train check --config configs/expanded-20261016/v3-bucket16.json
```

To start a new run yourself later:

```powershell
.\.venv\Scripts\python.exe -u -m stockbear.expanded_train train --config configs/expanded-20261016/v3-bucket16.json
# Resume its last complete epoch after interruption:
.\.venv\Scripts\python.exe -u -m stockbear.expanded_train train --config configs/expanded-20261016/v3-bucket16.json --resume
```

Substitute `v2.json` or `v3-full.json` to select another prepared format. Runs
write only beneath `runs/expanded-20261016/`, use validation for selection, and
leave test performance evaluation, network export and engine replacement for
separate explicit work. The configurations carry forward existing training
settings; this preparation does not claim an accuracy or Elo improvement.
