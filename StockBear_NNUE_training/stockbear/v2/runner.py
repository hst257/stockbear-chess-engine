from __future__ import annotations

import json
import math
import shutil
import time
from pathlib import Path

from ..common import save_json
from .label import label
from .learn import fit,evaluate_saved
from .verify import quality,integrity,export_candidate,protect_v1


def run(root:Path,cfg:dict):
    reports=root/cfg["reports"]
    bench=json.loads((reports/"label_benchmark.json").read_text())
    maximum=bench["largest_practical"]
    if maximum<200000: raise RuntimeError("Insufficient practical pool for the requested 200K experiment")
    results=[]
    def note(stage,**fields):
        save_json(reports/"execution_status.json",{"stage":stage,"unix_time":time.time(),**fields})
        print(json.dumps({"stage":stage,**fields}),flush=True)
    def experiment(name,size,architecture,overrides=None,seed=None):
        note("training",experiment=name,size=size,architecture=architecture)
        report=fit(root,cfg,name,size,architecture,seed=seed,overrides=overrides)
        results.append(report)
        save_json(reports/"experiment_index.json",results)
        return report
    note("pilot_label_checkpoint")
    pilot_manifest=reports/"pilot_completed.json"
    if not pilot_manifest.exists():
        label(root,cfg,4096,limit=64)
        label(root,cfg,4096)
        integrity(root,cfg,4096)
        pilot_settings={"epochs":20,"patience":5}
        fit(root,cfg,"pilot_v2",4096,"compact",overrides=pilot_settings,stop_after=2)
        pilot=fit(root,cfg,"pilot_v2",4096,"compact",overrides=pilot_settings)
        exported=export_candidate(root,cfg,"pilot_v2","compact",4096)
        save_json(pilot_manifest,{"training":pilot,"export":exported,"label_resume":True,"cuda_resume":True})
    note("teacher_quality")
    quality(root,cfg)
    for size in cfg["sizes"]:
        if size>maximum: continue
        note("labeling",size=size)
        label_path=reports/f"labels_{size}.json"
        if not label_path.exists() or json.loads(label_path.read_text())["missing"]:
            label(root,cfg,size)
        integrity_path=reports/f"integrity_{size}.json"
        if not integrity_path.exists(): integrity(root,cfg,size)
        experiment(f"scale_compact_{size}",size,"compact")
        if size==500000:
            for architecture in ("small","medium","large"):
                width=cfg["architectures"][architecture][0]
                learning_rate=.0015*min(1,math.sqrt(64/width))
                experiment(f"arch_{architecture}_{size}",size,architecture,{"learning_rate":learning_rate})
    common_size=500000 if maximum>=500000 else 200000
    comparable=[row for row in results if row["size"]==common_size]
    comparable.sort(key=lambda row:row["metrics"]["validation"]["blended_mse"])
    top=comparable[:cfg["search_budget"]["final_architectures"]]
    note("final_dataset_labeling",size=maximum)
    if not (reports/f"labels_{maximum}.json").exists(): label(root,cfg,maximum)
    if not (reports/f"integrity_{maximum}.json").exists(): integrity(root,cfg,maximum)
    contenders=[]
    for candidate in top:
        architecture=candidate["architecture"]
        base_lr=candidate["signature"]["training"]["learning_rate"]
        variants=[]
        for variant,changes in (("base",{"learning_rate":base_lr}),
                                ("regularized",{"learning_rate":base_lr*.5,"weight_decay":.1})):
            result=experiment(f"final_{architecture}_{maximum}_{variant}",maximum,architecture,changes)
            variants.append((result,changes))
        winner,changes=min(variants,key=lambda pair:pair[0]["metrics"]["validation"]["blended_mse"])
        repeated=experiment(winner["name"]+"_seed2",maximum,architecture,changes,seed=cfg["seed"]+1)
        mean=(winner["metrics"]["validation"]["blended_mse"]+repeated["metrics"]["validation"]["blended_mse"])/2
        contenders.append({"architecture":architecture,"primary":winner["name"],"repeat":repeated["name"],
                           "validation_mean_blended_mse":mean,"primary_validation":winner["metrics"]["validation"]["blended_mse"],
                           "repeat_validation":repeated["metrics"]["validation"]["blended_mse"],"size":maximum})
    contenders.sort(key=lambda row:row["validation_mean_blended_mse"])
    # Refuse to make a new selection if test files already exist without a saved choice.
    selection_path=reports/"selection.json"
    selection={"criterion":"mean validation blended MSE across two recorded seeds; primary seed exported",
               "test_used_for_selection":False,"contenders":contenders,"best":contenders[0],
               "bounded_search":cfg["search_budget"],"final_size":maximum}
    if selection_path.exists():
        if json.loads(selection_path.read_text())!=selection: raise ValueError("Immutable selection changed")
    else:
        if any((root/cfg["runs"]).glob("*/test_metrics.json")): raise RuntimeError("Unexpected preselection test evaluation")
        save_json(selection_path,selection)
    note("final_test_evaluation",selected=[x["primary"] for x in contenders])
    for candidate in contenders:
        name=candidate["primary"]
        if not (root/cfg["runs"]/name/"test_metrics.json").exists(): evaluate_saved(root,cfg,name,maximum)
    if not (root/cfg["runs"]/"v1_reference/test_metrics.json").exists():
        evaluate_saved(root,cfg,"v1_reference",maximum,checkpoint=root/"runs/compact/best.pt")
    if not (root/cfg["runs"]/"v1_reference/validation_metrics.json").exists():
        evaluate_saved(root,cfg,"v1_reference",maximum,split="validation",checkpoint=root/"runs/compact/best.pt")
    note("export")
    exports=[]
    architecture_winners={r["architecture"]:r for r in comparable}
    by_name={r["name"]:r for r in results}
    for contender in contenders: architecture_winners[contender["architecture"]]=by_name[contender["primary"]]
    for architecture,result in architecture_winners.items():
        ex=export_candidate(root,cfg,result["name"],architecture,result["size"])
        exports.append({"experiment":result["name"],"architecture":architecture,**ex})
        source=root/ex["path"]
        alias=source.parent/f"stockbear-v2-{architecture}.sbnnue"
        if alias.exists() and alias.read_bytes()!=source.read_bytes(): raise RuntimeError("Refusing candidate alias overwrite")
        shutil.copy2(source,alias);shutil.copy2(source.with_suffix(".golden.json"),alias.with_suffix(".golden.json"))
    best_arch=contenders[0]["architecture"]
    best_source=root/"exports/v2"/f"stockbear-v2-{best_arch}.sbnnue"
    best_output=best_source.parent/"stockbear-v2-best.sbnnue"
    if best_output.exists() and best_output.read_bytes()!=best_source.read_bytes(): raise RuntimeError("Refusing best candidate overwrite")
    shutil.copy2(best_source,best_output)
    shutil.copy2(best_source.with_suffix(".golden.json"),best_output.with_suffix(".golden.json"))
    save_json(reports/"exports.json",exports)
    protect_v1(root,cfg)
    note("reporting")
    from .report import finish
    final=finish(root,cfg,results,selection,exports)
    note("complete",result=final)
    return final
