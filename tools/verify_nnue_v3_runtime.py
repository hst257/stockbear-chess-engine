"""Verify the ordinary app runtime retains its original model and behavior."""
from contextlib import ExitStack
import json
from pathlib import Path

from app.engine_client import DEFAULT_ENGINE
from tools.nnue_diagnosis import BASE_OPTIONS, capture, metadata, open_engine, positions
from tools.profile_nnue_diagnosis import canonical


def main() -> None:
    out = Path("docs/nnue-v3/application-runtime.json")
    if out.exists():
        raise FileExistsError(out)
    original = Path("artifacts/nnue-v3/runtime-before/chesslab-engine.exe")
    before, after = metadata(original), metadata(DEFAULT_ENGINE)
    assert before["build"]["nnue"]["sha256"] == after["build"]["nnue"]["sha256"]
    result = {"before": before, "after": after, "same_embedded_model": True, "searches": [],
        "note": "Ordinary runtime retains original v1 embedded weights and classical default while adding separate v3 loading. Study release embeds optimized v2 explicitly."}
    with ExitStack() as stack:
        engines = [stack.enter_context(open_engine(p)) for p in (original, DEFAULT_ENGINE)]
        assert all(e.options["Evaluator"].default == "classical" for e in engines)
        for evaluator in ("classical", "nnue"):
            for engine in engines: engine.configure(BASE_OPTIONS | {"Evaluator": evaluator})
            for row in positions()[::3]:
                for mode,budget in (("depth",4),("nodes",100000)):
                    assert canonical(capture(engines[0],row,mode,budget)) == canonical(capture(engines[1],row,mode,budget))
                    result["searches"].append({"evaluator":evaluator,"position":row["id"],"mode":mode,"budget":budget,"identical":True})
    out.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print("Preserved",len(result["searches"]),"ordinary runtime searches and original model/default")


if __name__ == "__main__":
    main()
