from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import chess
import numpy as np
import torch

from ..common import connect,digest,file_hash,save_json
from ..features import FEATURE_VERSION,MAX_ACTIVE,encode
from ..model import NNUE
from ..teacher import teacher_profile
from ..train import seed_everything,target,atomic_checkpoint

_RESIDENT={}
PHASES=("opening","middlegame","endgame")


def prepare(root:Path,cfg:dict,size:int):
    directory=root/cfg["prepared"]/str(size)
    manifest_path=directory/"manifest.json"
    profile_id=digest(json.dumps(teacher_profile(root,cfg),sort_keys=True))
    db=connect(root/cfg["cache"])
    db.execute("ATTACH DATABASE ? AS pool",(str(root/cfg["pool"]),))
    signature={"profile":profile_id,"size":size,"features":FEATURE_VERSION,
               "pool":db.execute("SELECT value FROM pool.metadata WHERE key='pool_signature'").fetchone()[0]}
    if manifest_path.exists():
        report=json.loads(manifest_path.read_text())
        if report["signature"]!=signature: raise ValueError("Prepared dataset signature differs")
        db.close(); return directory,report
    missing=db.execute("""SELECT count(*) FROM pool.positions p LEFT JOIN labels l ON l.id=p.id AND l.profile=?
        WHERE p.ordinal<=? AND l.cp IS NULL""",(profile_id,size)).fetchone()[0]
    if missing: raise RuntimeError(f"{missing} labels missing before feature preparation")
    directory.mkdir(parents=True,exist_ok=True)
    holdout_size=min(min(cfg["sizes"]),size)
    game_map={gid:i for i,(gid,) in enumerate(db.execute("SELECT DISTINCT game_id FROM pool.positions ORDER BY game_id"))}
    report={"signature":signature,"splits":{},"nominal_pool_positions":size,"common_holdout_prefix":holdout_size}
    content=hashlib.sha256()
    for split in ("train","validation","test"):
        bound=size if split=="train" else holdout_size
        count=db.execute("SELECT count(*) FROM pool.positions WHERE split=? AND ordinal<=?",(split,bound)).fetchone()[0]
        if count<20: raise RuntimeError(f"Insufficient {split} positions: {count}")
        x=np.lib.format.open_memmap(directory/f"{split}_x.npy",mode="w+",dtype=np.uint16,shape=(count,2,MAX_ACTIVE))
        y=np.lib.format.open_memmap(directory/f"{split}_y.npy",mode="w+",dtype=np.float32,shape=(count,8))
        ordinal=np.lib.format.open_memmap(directory/f"{split}_ordinal.npy",mode="w+",dtype=np.int64,shape=(count,))
        query="""SELECT p.id,p.fen,l.cp,p.outcome,p.ply,p.phase,p.category,p.source,p.game_id,p.ordinal
            FROM pool.positions p JOIN labels l ON l.id=p.id AND l.profile=?
            WHERE p.split=? AND p.ordinal<=? ORDER BY p.ordinal"""
        for i,(pid,fen,cp,outcome,ply,phase,category,source,gid,order) in enumerate(db.execute(query,(profile_id,split,bound))):
            board=chess.Board(fen)
            material=sum((1 if pc.color==board.turn else -1)*[0,100,320,330,500,900,0][pc.piece_type] for pc in board.piece_map().values())
            x[i]=encode(board)
            y[i]=cp,outcome,material,ply,PHASES.index(phase),int(category=="tactical_heuristic"),int(Path(source).name[-15:-11]),game_map[gid]
            ordinal[i]=order
            content.update(f"{pid}:{cp}:{outcome}:{split}".encode())
        x.flush();y.flush();ordinal.flush()
        report["splits"][split]={"positions":count,"x_sha256":file_hash(directory/f"{split}_x.npy"),
                                  "y_sha256":file_hash(directory/f"{split}_y.npy")}
    report["fingerprint"]=content.hexdigest()
    save_json(manifest_path,report)
    db.close()
    return directory,report


def resident(root,cfg,size):
    if _RESIDENT.get("size")==size: return _RESIDENT["data"],_RESIDENT["directory"],_RESIDENT["manifest"]
    _RESIDENT.clear()
    torch.cuda.empty_cache()
    directory,manifest=prepare(root,cfg,size)
    data={}
    for split in ("train","validation","test"):
        x=np.load(directory/f"{split}_x.npy",mmap_mode="r")
        y=np.load(directory/f"{split}_y.npy",mmap_mode="r")
        if file_hash(directory/f"{split}_x.npy")!=manifest["splits"][split]["x_sha256"]: raise ValueError("Corrupt prepared features")
        if file_hash(directory/f"{split}_y.npy")!=manifest["splits"][split]["y_sha256"]: raise ValueError("Corrupt prepared targets")
        data[split]=(torch.tensor(np.asarray(x,dtype=np.int64),device="cuda"),torch.tensor(np.asarray(y),device="cuda"))
    _RESIDENT.update(size=size,data=data,directory=directory,manifest=manifest)
    return data,directory,manifest


def statistics(prediction,y,teacher_weight=.9):
    prediction=np.asarray(prediction,dtype=np.float64)
    y=np.asarray(y,dtype=np.float64)
    cp=np.clip(y[:,0],-2000,2000)
    pcp=np.clip(prediction,-2000,2000)
    prob=1/(1+np.exp(-np.clip(prediction/400,-80,80)))
    teacher=1/(1+np.exp(-cp/400))
    desired=teacher_weight*teacher+(1-teacher_weight)*y[:,1]
    error=pcp-cp
    decisive=np.abs(cp)>=100
    corr=float(np.corrcoef(cp,pcp)[0,1]) if len(cp)>1 and np.std(cp)>0 and np.std(pcp)>0 else None
    report={"positions":len(y),"blended_mse":float(np.mean((prob-desired)**2)),
            "teacher_probability_mse":float(np.mean((prob-teacher)**2)),"clipped_cp_mae":float(np.mean(np.abs(error))),
            "clipped_cp_rmse":float(np.sqrt(np.mean(error**2))),"clipped_cp_pearson":corr,
            "sign_accuracy_abs_cp_ge_100":float(np.mean((prediction[decisive]>0)==(cp[decisive]>0))) if decisive.any() else None,
            "material_baseline_teacher_mse":float(np.mean((1/(1+np.exp(-y[:,2]/400))-teacher)**2)),
            "prediction_cp_percentiles":np.percentile(prediction,[0,5,50,95,100]).tolist()}
    return report


@torch.inference_mode()
def predict(model,x,batch_size=8192):
    model.eval()
    return np.concatenate([model(x[i:i+batch_size]).cpu().numpy()*400 for i in range(0,len(x),batch_size)])


def detailed(prediction,y,weight):
    result=statistics(prediction,y,weight)
    result["by_phase"]={phase:statistics(prediction[y[:,4]==i],y[y[:,4]==i],weight)
                        for i,phase in enumerate(PHASES) if np.any(y[:,4]==i)}
    result["by_category"]={name:statistics(prediction[y[:,5]==i],y[y[:,5]==i],weight)
                           for i,name in enumerate(("quiet_heuristic","tactical_heuristic")) if np.any(y[:,5]==i)}
    result["by_year"]={str(int(year)):statistics(prediction[y[:,6]==year],y[y[:,6]==year],weight) for year in np.unique(y[:,6])}
    return result


def fit(root:Path,cfg:dict,name:str,size:int,architecture:str,seed:int|None=None,overrides:dict|None=None,stop_after:int|None=None):
    started=time.monotonic()
    seed=cfg["seed"] if seed is None else seed
    seed_everything(seed)
    if not torch.cuda.is_available(): raise RuntimeError("The audited v2 execution requires CUDA")
    data,directory,manifest=resident(root,cfg,size)
    tc={**cfg["training"],**(overrides or {})}
    width,hidden=cfg["architectures"][architecture]
    run=root/cfg["runs"]/name
    run.mkdir(parents=True,exist_ok=True)
    signature={"dataset":manifest["fingerprint"],"seed":seed,"training":tc,"width":width,"hidden":hidden,"features":FEATURE_VERSION,
               "torch":torch.__version__,"gpu":torch.cuda.get_device_name(0)}
    metrics_path=run/"metrics.json"
    if metrics_path.exists():
        existing=json.loads(metrics_path.read_text())
        if existing["signature"]!=signature: raise ValueError(f"Changed completed experiment {name}")
        return existing
    model=NNUE(width,hidden).cuda()
    optimizer=torch.optim.AdamW(model.parameters(),lr=tc["learning_rate"],weight_decay=tc["weight_decay"],fused=True)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=tc["scheduler_patience"],factor=.5,min_lr=1e-5)
    history=[]; best=float("inf");bad=0;first=0;previous_peak=0
    if (run/"last.pt").exists():
        state=torch.load(run/"last.pt",map_location="cuda",weights_only=False)
        if state["signature"]!=signature: raise ValueError("Resume signature mismatch")
        model.load_state_dict(state["model"]);optimizer.load_state_dict(state["optimizer"]);scheduler.load_state_dict(state["scheduler"])
        history=state["history"];best=state["best"];bad=state["bad"];first=state["epoch"]+1
        torch.set_rng_state(state["cpu_rng"].cpu());torch.cuda.set_rng_state(state["gpu_rng"].cpu())
        previous_peak=state["peak_cuda_bytes"]
    torch.cuda.reset_peak_memory_stats()
    train_x,train_y=data["train"]
    val_x,val_y=data["validation"]
    host_val_y=val_y.cpu().numpy()
    epoch_limit=min(tc["epochs"],stop_after) if stop_after is not None else tc["epochs"]
    for epoch in range(first,epoch_limit):
        if bad>=tc["patience"]: break
        model.train()
        order=torch.from_numpy(np.random.default_rng(seed+epoch).permutation(len(train_y))).cuda()
        epoch_start=time.monotonic();loss_sum=0
        for begin in range(0,len(order),tc["batch_size"]):
            ids=order[begin:begin+tc["batch_size"]]
            optimizer.zero_grad(set_to_none=True)
            loss=(model(train_x[ids]).sigmoid()-target(train_y[ids],tc["teacher_weight"])).square().mean()
            if not torch.isfinite(loss): raise FloatingPointError("Nonfinite loss")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(),tc["gradient_clip"],error_if_nonfinite=True)
            optimizer.step()
            loss_sum+=loss.item()*len(ids)
        val_prediction=predict(model,val_x)
        val=statistics(val_prediction,host_val_y,tc["teacher_weight"])
        score=val["blended_mse"]
        improved=score<best-tc["min_delta"]
        best,bad=(score,0) if improved else (best,bad+1)
        scheduler.step(score)
        row={"epoch":epoch+1,"train_mse":loss_sum/len(train_y),"validation_mse":score,
             "validation_teacher_mse":val["teacher_probability_mse"],"validation_cp_mae":val["clipped_cp_mae"],
             "seconds":time.monotonic()-epoch_start,"examples_processed":len(train_y)*(epoch+1),
             "learning_rate":optimizer.param_groups[0]["lr"]}
        history.append(row)
        state={"signature":signature,"model":model.state_dict(),"optimizer":optimizer.state_dict(),"scheduler":scheduler.state_dict(),
               "epoch":epoch,"best":best,"bad":bad,"history":history,"model_config":{"width":width,"hidden":hidden},
               "cpu_rng":torch.get_rng_state(),"gpu_rng":torch.cuda.get_rng_state(),
               "peak_cuda_bytes":max(previous_peak,torch.cuda.max_memory_allocated())}
        if improved: atomic_checkpoint(run/"best.pt",state)
        atomic_checkpoint(run/"last.pt",state)
        save_json(run/"history.json",history)
        print(json.dumps({"experiment":name,**row}),flush=True)
    if stop_after is not None and epoch_limit<tc["epochs"] and bad<tc["patience"]:
        return {"status":"checkpointed","name":name,"epochs":len(history)}
    state=torch.load(run/"best.pt",map_location="cuda",weights_only=False)
    model.load_state_dict(state["model"])
    metrics={}
    for split in ("train","validation"):
        prediction=predict(model,data[split][0])
        np.save(run/f"{split}_predictions.npy",prediction)
        metrics[split]=detailed(prediction,data[split][1].cpu().numpy(),tc["teacher_weight"])
    seconds=sum(row["seconds"] for row in history)
    report={"status":"complete","name":name,"architecture":architecture,"size":size,"seed":seed,"signature":signature,
            "parameters":sum(p.numel() for p in model.parameters()),"epochs":len(history),"best_epoch":state["epoch"]+1,
            "examples_processed":len(train_y)*len(history),"training_epoch_seconds":seconds,
            "examples_per_second":len(train_y)*len(history)/max(seconds,.001),"seconds_this_invocation":time.monotonic()-started,
            "peak_cuda_bytes":max(previous_peak,torch.cuda.max_memory_allocated()),"metrics":metrics,
            "generalization_gap":metrics["validation"]["blended_mse"]-metrics["train"]["blended_mse"],
            "test_evaluated":False,"model_config":{"width":width,"hidden":hidden},
            "dense_head_macs":2*width*hidden+hidden,"typical_quiet_incremental_adds":4*width,
            "prepared":str(directory.relative_to(root)),"torch":torch.__version__,"device":"cuda"}
    save_json(metrics_path,report)
    return report


def evaluate_saved(root,cfg,name,size,split="test",checkpoint=None):
    seed_everything(cfg["seed"])
    data,directory,manifest=resident(root,cfg,size)
    path=checkpoint or root/cfg["runs"]/name/"best.pt"
    state=torch.load(path,map_location="cuda",weights_only=False)
    model=NNUE(**state["model_config"]).cuda();model.load_state_dict(state["model"])
    prediction=predict(model,data[split][0])
    y=data[split][1].cpu().numpy()
    report=detailed(prediction,y,cfg["training"]["teacher_weight"])
    run=root/cfg["runs"]/name
    run.mkdir(parents=True,exist_ok=True)
    np.save(run/f"{split}_predictions.npy",prediction)
    save_json(run/f"{split}_metrics.json",report)
    return report
