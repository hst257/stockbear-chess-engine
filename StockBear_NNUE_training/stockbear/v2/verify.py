from __future__ import annotations

import collections
import concurrent.futures
import hashlib
import importlib.util
import json
import struct
from pathlib import Path

import chess
import numpy as np
import torch

from ..common import connect,digest,file_hash,metadata,save_json
from ..export import MAGIC,load_export,numpy_predict
from ..features import FEATURE_VERSION,FEATURES,encode
from ..model import NNUE
from ..teacher import find_teacher,teacher_profile
from .label import ScaleWorker,setup


def quality(root,cfg):
    output=root/cfg["reports"]/"teacher_quality.json"
    if output.exists(): return json.loads(output.read_text())
    db,profile,pid=setup(root,cfg)
    rows=db.execute("""SELECT p.id,p.fen,p.phase,p.category,l.cp,l.mate FROM pool.positions p
        JOIN labels l ON l.id=p.id AND l.profile=? WHERE p.ordinal<=200000 ORDER BY p.ordinal LIMIT 4096""",(pid,)).fetchall()
    buckets=collections.defaultdict(list)
    for row in rows:
        score_bin="mate" if row[5] is not None else "0-100" if abs(row[4])<=100 else "101-500" if abs(row[4])<=500 else "501+"
        buckets[(row[2],row[3],score_bin)].append(row)
    selected=[]
    for i in range(cfg["quality_positions"]):
        for key in sorted(buckets):
            if i<len(buckets[key]): selected.append(buckets[key][i])
            if len(selected)>=cfg["quality_positions"]: break
        if len(selected)>=cfg["quality_positions"]: break
    stronger={**cfg,"teacher":{**cfg["teacher"],"nodes":cfg["quality_nodes"]}}
    profile_high=teacher_profile(root,stronger)
    high_id=digest(json.dumps(profile_high,sort_keys=True))
    metadata(db,f"profile:{high_id}",profile_high)
    bench=json.loads((root/cfg["reports"]/"label_benchmark.json").read_text())
    worker=ScaleWorker(find_teacher(root),profile_high)
    try:
        with concurrent.futures.ThreadPoolExecutor(bench["selected_workers"]) as pool:
            higher=list(pool.map(worker,[(row[0],row[1],0) for row in selected]))
    finally: worker.close()
    if any(row[1] is None for row in higher): raise RuntimeError("Higher-budget teacher comparison failed")
    db.executemany("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",[(high_id,*row) for row in higher]);db.commit()
    records=[]
    for row,high in zip(selected,higher):
        cp,cp_high=row[4],high[1]
        delta_prob=1/(1+np.exp(-np.clip(cp,-2000,2000)/400))-1/(1+np.exp(-np.clip(cp_high,-2000,2000)/400))
        records.append({"id":row[0],"phase":row[2],"category":row[3],"base_cp":cp,"higher_cp":cp_high,
                        "base_mate":row[5],"higher_mate":high[2],"abs_cp_change":abs(cp-cp_high),
                        "clipped_abs_cp_change":float(abs(np.clip(cp,-2000,2000)-np.clip(cp_high,-2000,2000))),
                        "probability_squared_change":float(delta_prob**2)})
    def stats(group):
        return {"positions":len(group),"mean_abs_cp_change":float(np.mean([r["abs_cp_change"] for r in group])),
                "mean_clipped_abs_cp_change":float(np.mean([r["clipped_abs_cp_change"] for r in group])),
                "teacher_probability_mse_between_budgets":float(np.mean([r["probability_squared_change"] for r in group])),
                "mate_status_changes":sum((r["base_mate"] is None)!=(r["higher_mate"] is None) for r in group)}
    report={"base_nodes":profile["nodes"],"higher_nodes":profile_high["nodes"],"summary":stats(records),"groups":{},"records":records,
            "higher_budget_is_not_ground_truth":True}
    for axis in ("phase","category"):
        report["groups"][axis]={key:stats([r for r in records if r[axis]==key]) for key in sorted({r[axis] for r in records})}
    for key,predicate in {"abs_cp_le_100":lambda r:abs(r["base_cp"])<=100,"abs_cp_101_500":lambda r:100<abs(r["base_cp"])<=500,
                          "abs_cp_gt_500":lambda r:abs(r["base_cp"])>500,"mate_proximity":lambda r:r["base_mate"] is not None or r["higher_mate"] is not None}.items():
        group=[r for r in records if predicate(r)]
        if group: report["groups"][key]=stats(group)
    save_json(output,report);db.close();return report


def integrity(root,cfg,size):
    db,p,pid=setup(root,cfg)
    overlap=db.execute("SELECT count(*) FROM (SELECT game_id FROM pool.positions GROUP BY game_id HAVING count(DISTINCT split)>1)").fetchone()[0]
    duplicates=db.execute("SELECT count(*) FROM (SELECT fen FROM pool.positions GROUP BY fen HAVING count(*)>1)").fetchone()[0]
    missing=db.execute("SELECT count(*) FROM pool.positions p LEFT JOIN labels l ON l.id=p.id AND l.profile=? WHERE p.ordinal<=? AND l.cp IS NULL",(pid,size)).fetchone()[0]
    invalid=0
    for position_id,fen in db.execute("SELECT id,fen FROM pool.positions WHERE ordinal<=?",(size,)):
        board=chess.Board(fen)
        invalid+=int(not board.is_valid() or position_id!=digest(fen))
    old=connect(root/"data/processed/full.sqlite")
    old.execute("ATTACH DATABASE ? AS pool",(str(root/cfg["pool"]),))
    v1_leak=old.execute("SELECT count(*) FROM positions p JOIN pool.positions n USING(id) WHERE p.split='train' AND n.split!='train'").fetchone()[0]
    report={"size":size,"game_overlap":overlap,"exact_duplicates":duplicates,"missing_labels":missing,
            "invalid_or_corrupt_positions":invalid,"v1_training_positions_in_v2_holdouts":v1_leak}
    if any((overlap,duplicates,missing,invalid,v1_leak)): raise AssertionError(report)
    save_json(root/cfg["reports"]/f"integrity_{size}.json",report)
    db.close();old.close();return report


def export_candidate(root,cfg,name,architecture,size):
    run=root/cfg["runs"]/name
    checkpoint=torch.load(run/"best.pt",map_location="cpu",weights_only=False)
    model=NNUE(**checkpoint["model_config"]);model.load_state_dict(checkpoint["model"]);model.eval()
    payload=bytearray();tensors=[]
    for key,tensor in model.state_dict().items():
        array=np.ascontiguousarray(tensor.numpy(),dtype="<f4")
        tensors.append({"name":key,"shape":list(array.shape),"dtype":"<f4","offset":len(payload)})
        payload.extend(array.tobytes())
    header={"format":"StockBear float32 v1","feature_version":FEATURE_VERSION,"features":FEATURES,
            "model":checkpoint["model_config"],"score_pov":"side_to_move","output_cp_scale":400,
            "activation":"clip(x,0,1)","tensors":tensors,"payload_sha256":hashlib.sha256(payload).hexdigest(),
            "signature":checkpoint["signature"],"best_epoch":checkpoint["epoch"]+1,"experiment":name}
    encoded=json.dumps(header,sort_keys=True,separators=(",",":")).encode()
    data=MAGIC+struct.pack("<I",len(encoded))+encoded+payload
    output=root/"exports/v2"/f"stockbear-v2-{architecture}-{name}.sbnnue"
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.exists() and output.read_bytes()!=data: raise RuntimeError("Refusing to overwrite a different candidate")
    output.write_bytes(data)
    _,weights=load_export(output)
    db=connect(root/cfg["pool"])
    bound=min(size,min(cfg["sizes"]))
    rows=db.execute("SELECT fen FROM positions WHERE split='validation' AND ordinal<=? ORDER BY ordinal LIMIT 128",(bound,)).fetchall()
    golden=[];errors=[];device_errors=[]
    gpu_predictions=np.load(run/"validation_predictions.npy")
    with torch.inference_mode():
        for i,(fen,) in enumerate(rows):
            board=chess.Board(fen)
            cp=float(model(torch.from_numpy(encode(board)[None])).item()*400)
            errors.append(abs(cp-numpy_predict(board,weights)))
            device_errors.append(abs(cp-float(gpu_predictions[i])))
            golden.append({"fen":fen,"side_to_move_cp":cp})
    db.close()
    # Read-only validation by the actual native integration's existing parser.
    parser_path=root.parent/"tools/embed_nnue.py"
    spec=importlib.util.spec_from_file_location("stockbear_existing_native_parser",parser_path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.read_model(output)  # Does not generate a header or modify the engine.
    report={"path":str(output.relative_to(root)),"bytes":len(data),"sha256":file_hash(output),
            "payload_sha256":header["payload_sha256"],"parity_positions":len(rows),
            "max_numpy_cp_error":max(errors),"max_training_device_cp_error":max(device_errors),
            "native_format_reader_accepted":True,"native_inference_or_matches_run":False,"model":checkpoint["model_config"]}
    if max(errors+device_errors)>.01: raise AssertionError(report)
    save_json(output.with_suffix(".golden.json"),golden)
    save_json(run/"export_report.json",report)
    return report


def protect_v1(root,cfg):
    saved=json.loads((root/cfg["reports"]/"v1_protected.json").read_text())
    for path,checksum in saved.items():
        if file_hash(root/path)!=checksum: raise AssertionError(f"v1 artifact changed: {path}")
    report={"unchanged_v1_artifacts":len(saved),"all_hashes_match":True}
    save_json(root/cfg["reports"]/"v1_preservation.json",report)
    return report
