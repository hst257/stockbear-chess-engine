"""Contracts independent of the chosen embedded network or CPU ISA."""
import json
import hashlib
import struct
import subprocess
import sys
from pathlib import Path

import chess
import pytest

from tools.benchmark_nnue_v2 import POSITIONS, summary
from tools.validate_nnue_v2 import errors
from tools.embed_nnue import generate_header, read_model, quantize_tensors


def test_benchmark_categories_are_valid_orthodox_positions():
    assert len(POSITIONS) == 10
    assert all(chess.Board(fen).is_valid() for fen in POSITIONS.values())


def test_error_statistics_include_sign_and_phase_agnostic_units():
    assert errors([-1, 2], [1, 2]) == {"n": 2, "mae_cp": 1, "max_cp": 2,
                                      "rmse_cp": 2 ** .5, "sign_disagreements": 1}
    assert summary([{"nps": 1}, {"nps": 3}, {"nps": 2}], "nps")["median"] == 2


@pytest.mark.parametrize("name,width,hidden", [("compact", 32, 16), ("small", 64, 32)])
def test_bundled_v2_identity_and_transposed_layout(tmp_path, name, width, hidden):
    model = Path(f"engine/networks/v2/stockbear-v2-{name}.sbnnue")
    if not model.exists():
        # During development the original training export remains authoritative.
        model = Path(f"StockBear_NNUE_training/exports/v2/stockbear-v2-{name}.sbnnue")
    header, weights, checksum = read_model(model)
    assert header["model"]["width"] == width and header["model"]["hidden"] == hidden
    info = generate_header(model, tmp_path / "weights.hpp")
    assert info["sha256"] == checksum
    text = (tmp_path / "weights.hpp").read_text()
    transposed = text.split("float fc1_transposed[] = {", 1)[1].split("};", 1)[0]
    values = [float.fromhex(s.strip()[:-1]) for s in transposed.split(",") if s.strip()]
    assert values == [weights["fc1.weight"][h * 2 * width + j] for j in range(2 * width) for h in range(hidden)]
    assert len(json.loads(model.with_suffix(".golden.json").read_text())) == 128


@pytest.mark.parametrize("kernel", ["reference", "scalar", "quant", "auto"])
def test_kernel_switch_is_search_local_and_reproducible(engine, kernel):
    import chess.engine
    engine.configure({"Evaluator": "nnue", "NNUEKernel": kernel})
    a = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    engine.configure({"Evaluator": "classical"})
    engine.play(chess.Board(), chess.engine.Limit(depth=2))
    engine.configure({"Evaluator": "nnue", "NNUEKernel": kernel})
    b = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert (a.move, a.info["score"], a.info["nodes"]) == (b.move, b.info["score"], b.info["nodes"])


def test_forced_portable_fallback(engine_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("CHESSLAB_DISABLE_SIMD", "1")
    def value(kernel):
        return json.loads(subprocess.check_output([str(engine_path), "--eval", "--nnue", "--kernel", kernel, chess.STARTING_FEN], text=True))
    scalar, auto = (value(k) for k in ("scalar", "auto"))
    assert scalar == auto
    assert auto["kernel"] == "scalar"


@pytest.mark.parametrize("name", ["compact", "small"])
def test_quantized_overflow_proofs_include_all_active_rows(name):
    header, tensors, _ = read_model(Path(f"engine/networks/v2/stockbear-v2-{name}.sbnnue"))
    arrays, info = quantize_tensors(header, tensors)
    for key in ("accumulator_abs_bound", "head_abs_bound", "output_abs_bound"):
        assert info[key] < 2**31
    assert info["activation_scale"] < 32768
    assert all(-32768 <= v <= 32767 for kind, values in arrays.values() if kind == "std::int16_t" for v in values)
    assert all(v == 0 for v in arrays["q_transform_weight"][1][-header["model"]["width"]:])


def test_native_move_deltas_restore_siblings_and_maximum_feature_positions():
    subprocess.run([sys.executable, "tools/build_engine.py", "--target", "nnue-bench"], check=True, timeout=90)
    binary = Path("engine/build/chesslab-nnue-bench.exe").resolve()
    for kernel in ("scalar", "quant"):
        value = json.loads(subprocess.check_output([str(binary), "--verify", kernel], text=True, timeout=30))
        assert value["transitions"] > 30000 and value["nulls"] > 25000
        assert value["max_lane_error"] < .0001


def test_switching_integer_and_float_kernels_refreshes_roots(engine):
    import chess.engine
    engine.configure({"Evaluator": "nnue"})
    values = {}
    for kernel in ("reference", "quant", "scalar", "quant", "reference", "auto"):
        engine.configure({"NNUEKernel": kernel})
        result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        value = (result.move, result.info["score"], result.info["nodes"])
        if kernel in values:
            assert values[kernel] == value
        values[kernel] = value
    assert values["reference"] == values["scalar"] == values["auto"]


def test_optional_quantization_does_not_reject_a_valid_float_export(tmp_path):
    from tools.embed_nnue import DEFAULT_MODEL
    data = DEFAULT_MODEL.read_bytes()
    size, = struct.unpack_from("<I", data, 8)
    header = json.loads(data[12:12 + size])
    payload = bytearray(data[12 + size:])
    tensor = next(t for t in header["tensors"] if t["name"] == "transform.weight")
    struct.pack_into("<f", payload, tensor["offset"], 1e10)
    header["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    encoded = json.dumps(header).encode()
    model = tmp_path / "large-finite.sbnnue"
    model.write_bytes(data[:8] + struct.pack("<I", len(encoded)) + encoded + payload)
    info = generate_header(model, tmp_path / "weights.hpp")
    assert not info["quantization"]["supported"]
    assert "Q_ENABLED = false" in (tmp_path / "weights.hpp").read_text()


def test_quantized_dense_scale_reduces_before_int32_overflow():
    header, weights, _ = read_model(Path("engine/networks/v2/stockbear-v2-small.sbnnue"))
    weights["fc1.weight"] = [32.] * len(weights["fc1.weight"])
    _, info = quantize_tensors(header, weights)
    assert info["head_weight_scale"] < 4096 and info["head_abs_bound"] < 2**31
