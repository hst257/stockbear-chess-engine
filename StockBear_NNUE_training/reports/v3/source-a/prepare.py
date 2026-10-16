"""Read-only reuse of audited v2 examples and independently verify source FENs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time

import chess
import numpy as np

from .features import FEATURE_VERSION, MAX_ACTIVE, encode, from_v2


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def prepare(root: Path) -> dict:
    source = root / "data/v2/prepared/1250000"
    dest = root / "data/v3/full-halfkp"
    manifest = json.loads((source / "manifest.json").read_text())
    if (dest / "manifest.json").exists():
        result = json.loads((dest / "manifest.json").read_text())
        if result["source_manifest_sha256"] != sha(source / "manifest.json"):
            raise ValueError("Source manifest changed")
        for split, row in result["splits"].items():
            for kind in ("x", "y", "ordinal"):
                if sha(dest / f"{split}_{kind}.npy") != row[kind + "_sha256"]:
                    raise ValueError("Corrupt v3 prepared data")
        return result
    started = time.monotonic()
    dest.mkdir(parents=True, exist_ok=True)
    result = {"feature_version": FEATURE_VERSION, "source": str(source),
              "source_manifest_sha256": sha(source / "manifest.json"), "splits": {}}
    groups = {}
    db = sqlite3.connect(f"file:{(root / 'data/v2/pool.sqlite').as_posix()}?mode=ro", uri=True)
    for split in ("train", "validation", "test"):
        for kind in ("x", "y"):
            if sha(source / f"{split}_{kind}.npy") != manifest["splits"][split][kind + "_sha256"]:
                raise ValueError("Frozen v2 data checksum mismatch")
        x = np.load(source / f"{split}_x.npy", mmap_mode="r")
        out = np.lib.format.open_memmap(dest / f"{split}_x.npy", mode="w+", dtype=np.uint16,
                                       shape=(len(x), 2, MAX_ACTIVE))
        for start in range(0, len(x), 8192):
            out[start:start + 8192] = from_v2(x[start:start + 8192])
        out.flush()
        for kind in ("y", "ordinal"):
            target = dest / f"{split}_{kind}.npy"
            if target.exists() and sha(target) != sha(source / target.name):
                raise ValueError("Conflicting partial target file")
            shutil.copyfile(source / target.name, target)
        y = np.load(source / f"{split}_y.npy", mmap_mode="r")
        groups[split] = set(y[:, 7].astype(np.int64))
        ordinals = np.load(source / f"{split}_ordinal.npy", mmap_mode="r")
        # Deterministic evenly spread source positions, independent FEN parsing.
        selected = np.unique(np.linspace(0, len(out) - 1, min(4096, len(out)), dtype=int))
        for index in selected:
            fen, stored_split = db.execute("SELECT fen,split FROM positions WHERE ordinal=?",
                                            (int(ordinals[index]),)).fetchone()
            if stored_split != split or not np.array_equal(out[index], encode(chess.Board(fen))):
                raise AssertionError("Source FEN, split or feature contract mismatch")
        result["splits"][split] = {"positions": len(x), "source_fens_checked": len(selected),
            **{kind + "_sha256": sha(dest / f"{split}_{kind}.npy") for kind in ("x", "y", "ordinal")}}
        print("Re-encoded", split, len(x), "positions; verified", len(selected), "source FENs", flush=True)
    db.close()
    if any(groups[a] & groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise AssertionError("Grouped split leakage")
    result.update(grouped_splits_disjoint=True, original_targets_and_ordinals_identical=True,
                  seconds=time.monotonic() - started)
    (dest / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    reports = root / "reports/v3"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "dataset.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    prepare(Path(__file__).resolve().parents[2])
