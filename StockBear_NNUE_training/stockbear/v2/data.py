from __future__ import annotations

import collections
import hashlib
import heapq
import json
import math
import random
import time
from pathlib import Path

import chess
import chess.pgn

from ..common import connect, digest, file_hash, metadata, save_json
from ..sample import SelectedGameBuilder, canonical_fen, game_id, pgn_stream, split_for


def inventory(root: Path, cfg: dict) -> dict:
    """Read complete header streams, but parse just eight games per archive."""
    out = root / cfg["reports"] / "inventory.json"
    files = sorted((root / "data/raw").rglob("*"))
    files = [p for p in files if p.is_file()]
    previous = json.loads(out.read_text()) if out.exists() else {"archives": []}
    completed = {x["path"]: x for x in previous["archives"]}
    db = connect(root / cfg["pool"])
    db.execute("CREATE TABLE IF NOT EXISTS selected(source TEXT,gid TEXT,PRIMARY KEY(source,gid))")
    archives = []
    for path in files:
        relative = str(path.relative_to(root))
        selected_count = db.execute("SELECT count(*) FROM selected WHERE source=?", (relative,)).fetchone()[0]
        cached = completed.get(relative)
        if (cached is not None
                and cached["bytes"] == path.stat().st_size
                and cached.get("selection_limit", 2000) == cfg["games_per_archive"]
                and cached.get("selection_seed") == cfg["seed"]
                and selected_count == cached["selected_games"]):
            archives.append(cached)
            continue
        with path.open("rb") as f:
            magic = f.read(4).hex()
        frame_magic = int.from_bytes(bytes.fromhex(magic),"little")
        if not path.name.endswith(".pgn.zst") or not (magic == "28b52ffd" or 0x184D2A50 <= frame_magic <= 0x184D2A5F):
            raise ValueError(f"Unexpected input format: {relative}, magic={magic}")
        started = time.monotonic()
        heap, selected = [], set()
        count = 0
        headers_seen = collections.Counter()
        results = collections.Counter()
        with pgn_stream(path) as stream:
            while (headers := chess.pgn.read_headers(stream)) is not None:
                count += 1
                headers_seen.update(headers.keys())
                results[headers.get("Result", "missing")] += 1
                gid = game_id(headers)
                if gid in selected:
                    continue
                rank = int(digest(f"sample:{cfg['seed']}:{gid}"), 16)
                if len(heap) < cfg["games_per_archive"]:
                    heapq.heappush(heap, (-rank, gid))
                    selected.add(gid)
                elif rank < -heap[0][0]:
                    removed = heapq.heapreplace(heap, (-rank, gid))
                    selected.remove(removed[1])
                    selected.add(gid)
        samples = []
        eval_comments = 0
        with pgn_stream(path) as stream:
            for _ in range(8):
                game = chess.pgn.read_game(stream)
                if game is None:
                    break
                samples.append(dict(game.headers))
                eval_comments += sum("[%eval" in node.comment for node in game.mainline())
        entry = {"path": relative, "bytes": path.stat().st_size, "sha256": file_hash(path),
                 "format": "PGN", "compression": "zstd", "magic": magic, "games": count,
                 "selected_games": len(selected), "selection_limit":cfg["games_per_archive"], "selection_seed":cfg["seed"], "metadata_fields": dict(headers_seen),
                 "results": dict(results), "sample_headers": samples, "sample_eval_annotations": eval_comments,
                 "content": "Lichess broadcast games (per filename and PGN Event/Site metadata)",
                 "embedded_evals_used_as_targets": False, "seconds": time.monotonic()-started}
        db.execute("DELETE FROM selected WHERE source=?",(relative,))
        db.executemany("INSERT INTO selected VALUES (?,?)", [(relative, gid) for gid in selected])
        db.commit()
        archives.append(entry)
        save_json(out, {"archives": archives, "complete": False})
        print(f"Inventory {len(archives)}/{len(files)}: {path.name}, {count} games", flush=True)
    report = {"complete": True, "archive_count": len(archives), "compressed_bytes": sum(x["bytes"] for x in archives),
              "game_records": sum(x["games"] for x in archives), "archives": archives,
              "source_signature": digest(json.dumps([(x["path"],x["sha256"]) for x in archives]))}
    save_json(out, report)
    metadata(db, "inventory", {k:v for k,v in report.items() if k != "archives"})
    db.close()
    return report


def classify(board: chess.Board, ply: int, previous_move: chess.Move, previous_capture: bool) -> tuple[str,str,str]:
    pieces = len(board.piece_map())
    nonpawn = sum(len(board.pieces(pt, color)) * value for color in chess.COLORS
                  for pt, value in ((2,320),(3,330),(4,500),(5,900)))
    phase = "endgame" if pieces <= 10 or nonpawn <= 2600 else "opening" if ply <= 20 else "middlegame"
    check = board.is_check()
    captures = any(board.generate_legal_captures())
    flags = []
    if check: flags.append("in_check")
    if captures: flags.append("capture_available")
    if previous_capture: flags.append("after_capture")
    if previous_move.promotion: flags.append("after_promotion")
    material = [sum(len(board.pieces(pt,c))*v for pt,v in ((1,100),(2,320),(3,330),(4,500),(5,900))) for c in chess.COLORS]
    if abs(material[0]-material[1]) >= 100: flags.append("material_imbalance")
    passed = False
    promotion = False
    for color in chess.COLORS:
        for square in board.pieces(chess.PAWN,color):
            rank, file = chess.square_rank(square), chess.square_file(square)
            if (rank >= 5 if color else rank <= 2): promotion = True
            opposing = board.pieces(chess.PAWN,not color)
            if not any(abs(chess.square_file(other)-file) <= 1 and
                       (chess.square_rank(other)>rank if color else chess.square_rank(other)<rank) for other in opposing):
                passed = True
    if passed: flags.append("passed_pawn_heuristic")
    if promotion: flags.append("advanced_pawn")
    attacks = False
    for color in chess.COLORS:
        king = board.king(color)
        ring = chess.SquareSet(chess.BB_KING_ATTACKS[king] | chess.BB_SQUARES[king])
        if sum(bool(board.attackers(not color,sq)) for sq in ring) >= 3: attacks = True
    if attacks: flags.append("king_pressure_heuristic")
    standard_promoted_counts = any(len(board.pieces(pt,c))>limit for c in chess.COLORS for pt,limit in ((2,2),(3,2),(4,2),(5,1)))
    if standard_promoted_counts: flags.append("unusual_piece_configuration")
    return phase, "tactical_heuristic" if check or captures or previous_move.promotion or attacks else "quiet_heuristic", ",".join(flags)


def game_positions(game, cfg):
    outcome = {"1-0":1.0,"0-1":0.0,"1/2-1/2":0.5}.get(game.headers.get("Result"))
    if outcome is None or game.errors or game.headers.get("Variant","Standard") not in ("Standard","Chess"):
        return [], None
    board = game.board()
    if board.chess960 or not board.is_valid():
        return [], None
    initial = canonical_fen(board)
    moves = []
    buckets = collections.defaultdict(list)
    gid = game_id(game.headers)
    for ply, move in enumerate(game.mainline_moves(),1):
        capture = board.is_capture(move)
        moves.append(move.uci())
        board.push(move)
        if not cfg["min_ply"] <= ply <= cfg["max_ply"] or ply % cfg["ply_gap"]:
            continue
        if not board.is_valid() or board.is_game_over(claim_draw=False):
            continue
        phase, category, flags = classify(board, ply, move, capture)
        fen = canonical_fen(board)
        priority = digest(f"position:{cfg['seed']}:{gid}:{ply}:{fen}")
        buckets[(phase,category)].append((priority,fen,ply,outcome if board.turn else 1-outcome,phase,category,flags))
    for values in buckets.values(): values.sort()
    chosen = []
    for index in range(cfg["positions_per_game"]):
        for key in sorted(buckets):
            if index < len(buckets[key]):
                chosen.append(buckets[key][index])
                if len(chosen) >= cfg["positions_per_game"]:
                    return chosen, digest(initial+" "+" ".join(moves))
    return chosen, digest(initial+" "+" ".join(moves))


def build_pool(root: Path, cfg: dict):
    inv = json.loads((root/cfg["reports"]/"inventory.json").read_text())
    if not inv["complete"]: raise RuntimeError("Inventory incomplete")
    db = connect(root/cfg["pool"])
    db.executescript("""
      CREATE TABLE IF NOT EXISTS positions(id TEXT PRIMARY KEY,fen TEXT NOT NULL,game_id TEXT NOT NULL,
        split TEXT NOT NULL,source TEXT NOT NULL,ply INT NOT NULL,outcome REAL NOT NULL,
        phase TEXT NOT NULL,category TEXT NOT NULL,flags TEXT NOT NULL,priority TEXT NOT NULL,ordinal INT);
      CREATE TABLE IF NOT EXISTS games(gid TEXT PRIMARY KEY,moves TEXT NOT NULL);
    """)
    signature = {"sources":inv["source_signature"],"sampler":{k:cfg[k] for k in
                 ("seed","games_per_archive","positions_per_game","min_ply","max_ply","ply_gap")},"version":2}
    existing = metadata(db,"pool_signature")
    if existing is not None and existing != signature:
        prior_quota=existing["sampler"]["games_per_archive"]
        expanded=json.loads(json.dumps(existing))
        expanded["sampler"]["games_per_archive"]=cfg["games_per_archive"]
        if expanded!=signature or prior_quota>=cfg["games_per_archive"] or any((root/cfg["runs"]).glob("*/last.pt")):
            raise ValueError("Pool signature changed")
        metadata(db,"pool_sources",[])
        metadata(db,"pool_finalized",False)
        db.execute("DROP INDEX IF EXISTS ordinal_idx")
        db.commit()
    metadata(db,"pool_signature",signature)
    completed = metadata(db,"pool_sources") or []
    if metadata(db,"pool_finalized"):
        return metadata(db,"pool_report")
    started = time.monotonic()
    for item in inv["archives"]:
        source = item["path"]
        if source in completed: continue
        if file_hash(root/source) != item["sha256"]: raise ValueError(f"Source checksum changed: {source}")
        selected = {row[0] for row in db.execute("SELECT gid FROM selected WHERE source=?",(source,))}
        known = {row[0] for row in db.execute("SELECT gid FROM games")}
        selected.difference_update(known)
        positions_before = db.execute("SELECT count(*) FROM positions").fetchone()[0]
        with pgn_stream(root/source) as stream:
            while (game := chess.pgn.read_game(stream,Visitor=lambda:SelectedGameBuilder(selected))) is not None:
                gid = game_id(game.headers)
                if gid not in selected or gid in known: continue
                rows, moves_hash = game_positions(game,cfg)
                if moves_hash is None: continue
                known.add(gid)
                db.execute("INSERT OR IGNORE INTO games VALUES (?,?)",(gid,moves_hash))
                for priority,fen,ply,outcome,phase,category,flags in rows:
                    db.execute("INSERT OR IGNORE INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL)",
                        (digest(fen),fen,gid,split_for(gid,cfg["seed"]),source,ply,outcome,phase,category,flags,priority))
                if len(known)%100==0: db.commit()
        db.commit()
        completed.append(source)
        metadata(db,"pool_sources",completed)
        print(f"Pool {len(completed)}/{len(inv['archives'])}: {Path(source).name}, {db.execute('SELECT count(*) FROM positions').fetchone()[0]-positions_before} new positions",flush=True)
    # Identical complete move sequences with different headers share a partition.
    db.execute("ATTACH DATABASE ? AS v1",(str(root/"data/processed/full.sqlite"),))
    db.execute("CREATE INDEX IF NOT EXISTS game_idx ON positions(game_id)")
    old_groups = dict(db.execute("SELECT game_id,split FROM v1.positions GROUP BY game_id"))
    aliases = collections.defaultdict(list)
    for gid,moves in db.execute("SELECT gid,moves FROM games"): aliases[moves].append(gid)
    merged, conflicts = 0, 0
    for gids in aliases.values():
        anchored = {old_groups[g] for g in gids if g in old_groups}
        if len(anchored)>1:
            db.executemany("DELETE FROM positions WHERE game_id=?",[(g,) for g in gids]); conflicts+=1
            continue
        canonical = min((g for g in gids if g in old_groups),default=min(gids))
        split = next(iter(anchored)) if anchored else split_for(canonical,cfg["seed"])
        for gid in gids:
            if gid != canonical or split != split_for(gid,cfg["seed"]):
                db.execute("UPDATE positions SET game_id=?,split=? WHERE game_id=?",(canonical,split,gid))
        merged += len(gids)-1
    db.execute("DELETE FROM positions WHERE split!='train' AND id IN (SELECT id FROM v1.positions WHERE split='train')")
    db.commit()
    # Interleave normalized within-stratum ranks: all nested prefixes retain
    # approximately the pool's year/phase/category/split distribution.
    db.executescript("""
      DROP TABLE IF EXISTS ordered;
      CREATE TABLE ordered AS WITH ranked AS (
        SELECT id,priority,ROW_NUMBER() OVER(PARTITION BY substr(source,-15,4),phase,category,split ORDER BY priority) r,
               COUNT(*) OVER(PARTITION BY substr(source,-15,4),phase,category,split) n FROM positions
      ) SELECT id,ROW_NUMBER() OVER(ORDER BY (r-0.5)*1.0/n,priority) ordinal FROM ranked;
      CREATE UNIQUE INDEX ordered_id ON ordered(id);
      UPDATE positions SET ordinal=(SELECT ordinal FROM ordered WHERE ordered.id=positions.id);
      DROP TABLE ordered;
      CREATE UNIQUE INDEX IF NOT EXISTS ordinal_idx ON positions(ordinal);
      CREATE INDEX IF NOT EXISTS split_ordinal_idx ON positions(split,ordinal);
    """)
    counts = dict(db.execute("SELECT split,count(*) FROM positions GROUP BY split"))
    report = {"positions":sum(counts.values()),"splits":counts,"games":db.execute("SELECT count(DISTINCT game_id) FROM positions").fetchone()[0],
              "merged_game_aliases":merged,"conflicting_old_groups_excluded":conflicts,"seconds":time.monotonic()-started,
              "diversity":[dict(zip(("phase","category","count"),row)) for row in db.execute("SELECT phase,category,count(*) FROM positions GROUP BY phase,category")],
              "heuristics_are_not_verified_tactics":True,"signature":signature}
    metadata(db,"pool_report",report)
    metadata(db,"pool_finalized",True)
    save_json(root/cfg["reports"]/"pool_report.json",report)
    db.close()
    return report


def audit_metadata(root:Path,cfg:dict):
    """Classify source metadata without mistaking hints for verified labels."""
    inv=json.loads((root/cfg["reports"]/"inventory.json").read_text())
    output=root/cfg["reports"]/"source_metadata_audit.json"
    if output.exists(): return json.loads(output.read_text())
    engine_words=("stockfish","lc0","leela chess","tcec","ccrl","computer chess","komodo","ethereal","stoofvlees","koivisto","rubichess","rofchade")
    categories=collections.Counter();variants=collections.Counter();ratings=collections.Counter();archives=[]
    setup_count=0
    for item in inv["archives"]:
        local=collections.Counter();examples=[]
        with pgn_stream(root/item["path"]) as stream:
            while (headers:=chess.pgn.read_headers(stream)) is not None:
                text=" ".join(str(headers.get(k,"")) for k in ("Event","StudyName","White","Black")).casefold()
                kind="engine_like_metadata" if any(word in text for word in engine_words) else "puzzle_like_metadata" if "puzzle" in text else "ordinary_broadcast_metadata"
                local[kind]+=1;categories[kind]+=1
                variants[headers.get("Variant","Standard")]+=1
                setup_count+=int("FEN" in headers)
                if kind!="ordinary_broadcast_metadata" and len(examples)<5:
                    examples.append({k:headers.get(k) for k in ("Event","White","Black","Date")})
                for key in ("WhiteElo","BlackElo"):
                    try: rating=int(headers.get(key,""))
                    except ValueError: ratings["missing_or_nonnumeric"]+=1;continue
                    label="le_1800" if rating<=1800 else "1801_2200" if rating<=2200 else "2201_2600" if rating<=2600 else "2601_3000" if rating<=3000 else "gt_3000"
                    ratings[label]+=1
        archives.append({"path":item["path"],"categories":dict(local),"nonordinary_examples":examples})
    report={"categories":dict(categories),"variants":dict(variants),"player_rating_counts":dict(ratings),
            "setup_fen_records":setup_count,"archives":archives,"metadata_hints_are_not_verified_content_labels":True,
            "formats_detected":["PGN in Zstandard frames, including skippable prefixes"],"standalone_puzzle_format_detected":False}
    save_json(output,report)
    return report
