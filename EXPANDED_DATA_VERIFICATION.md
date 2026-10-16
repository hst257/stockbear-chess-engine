# Expanded NNUE corpus verification

## Result

**4,470,665/4,470,665 new positions have valid labels**;
zero pending positions, failed labels, teacher errors or source errors.
Total attempts: 4,470,665. The eight-worker session averaged
161.14 positions/s.

The original automatic post-processing was still running after labeling reached
zero remaining. It was stopped after confirming all labels were committed and
no Stockfish workers remained. This workflow completed independent read-only
integrity, foreign-key, profile, family/alias, result-perspective and range checks,
then validated **all 4,470,665 new FENs** in parallel.
Original SQLite checkpoints and labels were retained; no ingestion or labeling
was restarted. The original run may retain its `labeling` stage metadata, while
the new corpus's `source-audit.json` and `READY.json` record completed verification.

There are 22,253 recorded input-game skips,
primarily unsupported variants, no eligible sampled positions and unfinished
results. The only pipeline events are the two earlier Ctrl+C interruptions.
These are not failed Stockfish labels.

The preparation helper encountered a checkpointing error after the merged data
and validation report had committed. Its unqualified checkpoint included
read-only source attachments. The fix scopes checkpointing to the derived
database. A bounded compatibility check resumed the completed merge without
recopying rows, retained its saved signature and recorded both code versions.
Six focused preparation checks passed, including this recovery path.

Teacher profile: `ddc2b43b123677466a9a9f8478f67ffc028a6582266a73e36a3272bc85b30f92`. Stockfish 19, 16,384-node budget,
one thread and 64 MiB hash per engine; side-to-move centipawns, ±2000 mate
conversion, and `0.9 * sigmoid(clip(cp,-2000,2000)/400) + 0.1 * outcome` retained.
Raw cp range: -10,123 to 10,007;
27,430 mate labels; actual nodes 245–16,614.
The separate 65,536-node analysis profile was not merged.

## Merged corpus

| Origin | Compatible labeled rows | Unique retained rows |
| --- | ---: | ---: |
| v2 | 1,252,127 | 1,251,886 |
| v1 | 56,721 | 46,235 |
| expanded | 4,470,665 | 4,470,665 |

Old-corpus overlap: **10,486 positions**. The derived corpus
excludes **241 ambiguous position IDs**:
`{"conflicting frozen position splits": 31, "conflicting game outcomes": 210}`.
Known game-family split conflicts: **0**.
Sources are never deleted or reassigned.
`duplicate_provenance`, `exclusions`, `group_map` and the origin/owner/ordinal
columns in `merged.sqlite` retain the decisions and source links.

**5,768,786 unique positions are ready:**

| Split | Positions |
| --- | ---: |
| train | 4,616,965 |
| validation | 573,685 |
| test | 578,136 |

Game indices are mapped jointly, including stable IDs, complete-mainline aliases
and the original planner's recorded frozen-corpus anchors. Known families and
exact positions do not cross partitions. Raw game-result targets are preserved;
only ambiguous overlaps are excluded. Missing legacy v1 phase/category/year
metadata is derived from the board/source without changing its teacher target.

## Prepared data and handoff

Location: `StockBear_NNUE_training/data/expanded/cc-events-20261016/`.
All three formats contain identical target/ordinal rows, with independently
checked board encodings, shared game IDs, disjoint splits and file checksums.

- `v2`: 5,768,786 positions; fingerprint `99dc8cbe82f7fe529cbe219297891431e4c4fe4f65e601ca4ee504313aca8bdb`.
- `v3-bucket16`: 5,768,786 positions; fingerprint `9cb3430e2d0014ca72525a4ad2a5d976c1957ad94820c918a01314d2f27b96af`.
- `v3-full`: 5,768,786 positions; fingerprint `8ed0f9cf1f915cf77dcbf2f4dc6dcded6a83233405f4fcc2077bb368c463e62a`.

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
