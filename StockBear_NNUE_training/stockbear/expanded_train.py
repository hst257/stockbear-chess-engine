"""Explicit, opt-in training on the separately prepared expanded corpus."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
import time

import numpy as np

from .common import file_hash
from .labeling.storage import atomic_json, writer_lock

ROOT=Path(__file__).resolve().parents[1]


def verify_dataset(cfg: dict) -> tuple[Path, dict]:
    directory=(ROOT/cfg["dataset"]).resolve()
    ready=json.loads((directory.parents[1]/"READY.json").read_text(encoding="utf-8"))
    manifest=json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
    identity={k:v for k,v in manifest.items() if k!="fingerprint"}
    if hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()!=manifest["fingerprint"]:
        raise ValueError("Prepared manifest identity is corrupt")
    if not ready["complete"] or not ready["source_files_unchanged"]:
        raise ValueError("Expanded dataset has not passed preparation/preservation checks")
    if manifest["fingerprint"]!=ready["prepared"][cfg["format"]]["fingerprint"] or manifest["format"]!=cfg["format"]:
        raise ValueError("Dataset/configuration identity mismatch")
    for name,expected in manifest["files"].items():
        if file_hash(directory/name)!=expected:
            raise ValueError(f"Prepared data checksum mismatch: {name}")
    for split in ("train","validation","test"):
        x=np.load(directory/f"{split}_x.npy",mmap_mode="r")
        y=np.load(directory/f"{split}_y.npy",mmap_mode="r")
        width=37 if cfg["format"]=="v2" else 35
        if x.shape!=(manifest["splits"][split]["positions"],2,width) or y.shape!=(len(x),8) or x.dtype!=np.uint16 or y.dtype!=np.float32:
            raise ValueError("Prepared array contract mismatch")
        x._mmap.close();y._mmap.close()
    return directory,manifest


def fit(cfg: dict, resume: bool) -> dict:
    # Preparation/check commands never import a model, create an optimizer or run CUDA.
    import torch
    from .model import NNUE
    from .v3.model import KingRelativeNNUE
    from .train import atomic_checkpoint, batches, evaluate, seed_everything, target

    directory,manifest=verify_dataset(cfg)
    seed_everything(cfg["seed"])
    tc=cfg["training"]
    device="cuda" if torch.cuda.is_available() else "cpu"
    if tc["require_cuda"] and device!="cuda":
        raise RuntimeError("CUDA is required by this training configuration")
    run=(ROOT/cfg["run"]).resolve()
    if not run.is_relative_to((ROOT/"runs").resolve()) or run==(ROOT/"runs").resolve():
        raise ValueError("Use a separate run directory beneath runs/")
    if run.exists() and any(run.iterdir()) and not resume:
        raise ValueError("Training output exists; use --resume for its matching checkpoint")
    if resume and not (run/"last.pt").is_file():
        raise ValueError("No checkpoint exists for this requested resume")
    signature={"dataset":manifest["fingerprint"],"config":cfg,"torch":torch.__version__,"numpy":np.__version__,
        "device":device,"gpu":torch.cuda.get_device_name(0) if device=="cuda" else None,
        "code_sha256":{str(p.relative_to(ROOT)):file_hash(p) for p in
          (Path(__file__),ROOT/"stockbear/train.py",ROOT/"stockbear/model.py",ROOT/"stockbear/v3/model.py")}}
    model=NNUE(tc["width"],tc["hidden"]) if cfg["format"]=="v2" else KingRelativeNNUE(16 if cfg["format"]=="v3-bucket16" else 64)
    model=model.to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=tc["learning_rate"],weight_decay=tc["weight_decay"],fused=device=="cuda")
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=tc["scheduler_patience"],factor=.5,min_lr=1e-5)
    data={split:(np.load(directory/f"{split}_x.npy",mmap_mode="r"),np.load(directory/f"{split}_y.npy",mmap_mode="r")) for split in ("train","validation")}
    history=[];best=float("inf");bad=0;first=0
    with writer_lock(run):
        if resume:
            state=torch.load(run/"last.pt",map_location=device,weights_only=False)
            if state["signature"]!=signature:raise ValueError("Checkpoint/config/data/runtime identity mismatch")
            model.load_state_dict(state["model"]);optimizer.load_state_dict(state["optimizer"])
            scheduler.load_state_dict(state["scheduler"])
            history,best,bad,first=state["history"],state["best"],state["bad"],state["epoch"]+1
            random.setstate(state["python_rng"]);np.random.set_state(state["numpy_rng"])
            torch.set_rng_state(state["cpu_rng"].cpu())
            if device=="cuda":torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda_rng"]])
        for epoch in range(first,tc["epochs"]):
            if bad>=tc["patience"]:break
            started=time.monotonic();model.train();loss_sum=0;seen=0;last_tick=started
            order=np.random.default_rng(cfg["seed"]+epoch).permutation(len(data["train"][1]))
            for xb,yb in batches(*data["train"],tc["batch_size"],device,order):
                optimizer.zero_grad(set_to_none=True)
                loss=(model(xb).sigmoid()-target(yb,tc["teacher_weight"])).square().mean()
                if not torch.isfinite(loss):raise FloatingPointError("Nonfinite expanded training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(),tc["gradient_clip"],error_if_nonfinite=True)
                optimizer.step();loss_sum+=loss.item()*len(yb);seen+=len(yb)
                if time.monotonic()-last_tick>=30:
                    print(json.dumps({"epoch":epoch+1,"positions":seen,"total":len(order),"elapsed_seconds":time.monotonic()-started}),flush=True)
                    last_tick=time.monotonic()
            validation=evaluate(model,*data["validation"],tc,device)
            value=validation["blended_mse"]
            improved=value<best-tc["min_delta"]
            best,bad=(value,0) if improved else (best,bad+1)
            scheduler.step(value)
            row={"epoch":epoch+1,"train_mse":loss_sum/seen,"validation":validation,"seconds":time.monotonic()-started,
                 "learning_rate":optimizer.param_groups[0]["lr"]}
            history.append(row)
            state={"signature":signature,"model":model.state_dict(),"optimizer":optimizer.state_dict(),
                "scheduler":scheduler.state_dict(),"epoch":epoch,"best":best,"bad":bad,"history":history,
                "python_rng":random.getstate(),"numpy_rng":np.random.get_state(),"cpu_rng":torch.get_rng_state(),
                "cuda_rng":torch.cuda.get_rng_state_all() if device=="cuda" else [],"format":cfg["format"]}
            if improved:atomic_checkpoint(run/"best.pt",state)
            atomic_checkpoint(run/"last.pt",state)
            atomic_json(run/"history.json",history)
            print(json.dumps(row),flush=True)
        if not history:raise ValueError("No completed training epoch")
        result={"complete":True,"dataset":manifest["fingerprint"],"epochs":len(history),"best_validation_mse":best,
                "test_evaluated":False,"engine_or_existing_models_changed":False,"export_performed":False}
        atomic_json(run/"training.json",result)
        return result


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("check","train"))
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args()
    cfg=json.loads(args.config.read_text(encoding="utf-8"))
    if args.action=="check":
        directory,manifest=verify_dataset(cfg)
        print(json.dumps({"ready":True,"training_started":False,"dataset":str(directory),"format":cfg["format"],"splits":manifest["splits"]},indent=2))
    else:print(json.dumps(fit(cfg,args.resume),indent=2))


if __name__=="__main__":main()
