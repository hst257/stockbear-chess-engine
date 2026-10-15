import argparse
import json
from pathlib import Path

from ..common import load_config

def main():
    p=argparse.ArgumentParser()
    p.add_argument("command",choices=("inventory","pool","benchmark","label","run"))
    p.add_argument("--size",type=int)
    p.add_argument("--limit",type=int)
    args=p.parse_args()
    root=Path(__file__).resolve().parents[2]
    cfg=load_config(root/"configs/v2/plan.json")
    if args.command in ("inventory","pool"):
        from .data import inventory,build_pool
        result=(inventory if args.command=="inventory" else build_pool)(root,cfg)
    else:
        from .pipeline import dispatch
        result=dispatch(root,cfg,args)
    print(json.dumps({k:v for k,v in result.items() if k!='archives'},indent=2),flush=True)

if __name__=="__main__": main()
