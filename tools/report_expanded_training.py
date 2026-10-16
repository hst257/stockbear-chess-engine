"""Publish the completed local corpus audit without committing large data files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"StockBear_NNUE_training/data/expanded/cc-events-20261016"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    ready=read(DATA/"READY.json")
    audit=read(DATA/"source-audit.json")
    merge=read(DATA/"merge-report.json")
    assert ready["complete"] and ready["source_files_unchanged"] and not ready["training_started"]
    assert audit["all_fens_and_labels_checked"] and audit["source_fens_checked"]==4470665
    assert ready["merged"]==merge
    assert sum(merge["splits"].values())==merge["positions"]
    code_paths=[ROOT/"StockBear_NNUE_training/stockbear"/name for name in ("expanded_data.py","expanded_train.py")]
    configs=ROOT/"StockBear_NNUE_training/configs/expanded-20261016"
    loader_checks={fmt:json.loads((ROOT/"artifacts/labeling/expanded-20261016"/f"{fmt}-loader-check.json").read_text(encoding="utf-8-sig")) for fmt in ready["prepared"]}
    assert all(item["ready"] and not item["training_started"] for item in loader_checks.values())
    assert not (ROOT/"StockBear_NNUE_training/runs/expanded-20261016").exists()
    evidence={"source_audit":audit,"ready":ready,"merge":merge,
              "loader_checks":loader_checks,
              "preparation_runtime":read(DATA/"preparation-runtime.json") if (DATA/"preparation-runtime.json").exists() else None,
              "prepared_manifests":{fmt:read(DATA/"prepared"/fmt/"manifest.json") for fmt in ready["prepared"]},
              "configuration_files":{p.relative_to(ROOT).as_posix():read(p) for p in sorted(configs.glob("*.json"))},
              "source_lf_sha256":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n")).hexdigest() for p in code_paths},
              "data_files":"Large SQLite/NPY sources and outputs remain on the project drive and are intentionally not in Git."}
    path=ROOT/"docs/expanded-training-20261016.json"
    path.write_text(json.dumps(evidence,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    q=audit["quality"];ranges=audit["label_ranges"]
    splits="\n".join(f"| {split} | {merge['splits'][split]:,} |" for split in ("train","validation","test"))
    originals="\n".join(f"| {name} | {merge['source_counts'][name]:,} | {merge['inserted_by_origin'][name]:,} |" for name in ("v2","v1","expanded"))
    formats="\n".join(f"- `{fmt}`: {sum(row['positions'] for row in data['splits'].values()):,} positions; fingerprint `{data['fingerprint']}`."
                      for fmt,data in ready["prepared"].items())
    text=f'''# Expanded NNUE corpus verification

## Result

**{q['completed']:,}/{q['positions']:,} new positions have valid labels**;
zero pending positions, failed labels, teacher errors or source errors.
Total attempts: {ranges['attempts']:,}. The eight-worker session averaged
{audit['last_progress']['positions_per_second']:.2f} positions/s.

The original automatic post-processing was still running after labeling reached
zero remaining. It was stopped after confirming all labels were committed and
no Stockfish workers remained. This workflow completed independent read-only
integrity, foreign-key, profile, family/alias, result-perspective and range checks,
then validated **all {audit['source_fens_checked']:,} new FENs** in parallel.
Original SQLite checkpoints and labels were retained; no ingestion or labeling
was restarted. The original run may retain its `labeling` stage metadata, while
the new corpus's `source-audit.json` and `READY.json` record completed verification.

There are {audit['errors_by_stage'].get('game',0):,} recorded input-game skips,
primarily unsupported variants, no eligible sampled positions and unfinished
results. The only pipeline events are the two earlier Ctrl+C interruptions.
These are not failed Stockfish labels.

The preparation helper encountered a checkpointing error after the merged data
and validation report had committed. Its unqualified checkpoint included
read-only source attachments. The fix scopes checkpointing to the derived
database. A bounded compatibility check resumed the completed merge without
recopying rows, retained its saved signature and recorded both code versions.
Six focused preparation checks passed, including this recovery path.

Teacher profile: `{audit['profile_id']}`. Stockfish 19, 16,384-node budget,
one thread and 64 MiB hash per engine; side-to-move centipawns, ±2000 mate
conversion, and `0.9 * sigmoid(clip(cp,-2000,2000)/400) + 0.1 * outcome` retained.
Raw cp range: {ranges['cp_min']:,} to {ranges['cp_max']:,};
{ranges['mate_labels']:,} mate labels; actual nodes {ranges['nodes_min']:,}–{ranges['nodes_max']:,}.
The separate 65,536-node analysis profile was not merged.

## Merged corpus

| Origin | Compatible labeled rows | Unique retained rows |
| --- | ---: | ---: |
{originals}

Old-corpus overlap: **{merge['duplicates']:,} positions**. The derived corpus
excludes **{merge['excluded_position_ids']:,} ambiguous position IDs**:
`{json.dumps(merge['exclusions_by_reason'],sort_keys=True)}`.
Known game-family split conflicts: **{merge['groups']['conflicting_split_families']:,}**.
Sources are never deleted or reassigned.
`duplicate_provenance`, `exclusions`, `group_map` and the origin/owner/ordinal
columns in `merged.sqlite` retain the decisions and source links.

**{merge['positions']:,} unique positions are ready:**

| Split | Positions |
| --- | ---: |
{splits}

Game indices are mapped jointly, including stable IDs, complete-mainline aliases
and the original planner's recorded frozen-corpus anchors. Known families and
exact positions do not cross partitions. Raw game-result targets are preserved;
only ambiguous overlaps are excluded. Missing legacy v1 phase/category/year
metadata is derived from the board/source without changing its teacher target.

## Prepared data and handoff

Location: `StockBear_NNUE_training/data/expanded/cc-events-20261016/`.
All three formats contain identical target/ordinal rows, with independently
checked board encodings, shared game IDs, disjoint splits and file checksums.

{formats}

All five input databases (including any WAL content), saved signatures and
configurations match their before/after SHA256 snapshots. Existing models,
original prepared data and engine code are untouched. Large outputs remain on Z:.
The real CLI's data-only `check` action passed for all three configurations;
no new training run directory or checkpoints were created.

**No training, network export, engine replacement or strength testing occurred.**
The new loader reads memory-mapped batches instead of making the entire expanded
corpus resident on the GPU. Validation selects epochs; the test set is not scored
by the new training entry point. Existing experiment entry points remain frozen.

See [exact check/start/resume commands](EXPANDED_TRAINING_README.md).
[Reproducible counts, source hashes and configurations](docs/expanded-training-20261016.json).
'''
    (ROOT/"EXPANDED_DATA_VERIFICATION.md").write_text(text,encoding="utf-8",newline="\n")
    print("Published",path)


if __name__=="__main__":main()
