"""Validate the custom StockBear float32 export and emit exact C++ constants.

Uses only the standard library. Runtime inference needs neither Python nor Torch.
"""
import hashlib
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = ROOT / "engine/networks/stockbear-compact.sbnnue"
FEATURE_VERSION = "dual-perspective-12x64-castling-ep-v1"


def quantize_tensors(header: dict, tensors: dict) -> tuple[dict, dict]:
    """Derived experimental integers; original export bytes are never changed."""
    width, hidden = header["model"]["width"], header["model"]["hidden"]
    def nearest(v):
        return math.floor(v + .5) if v >= 0 else math.ceil(v - .5)
    def scale_for(values):
        scale = 4096
        while max(abs(v) for v in values) * scale > 32767 and scale > 1:
            scale //= 2
        if max(abs(v) for v in values) * scale > 32767:
            raise ValueError("Quantized weights exceed int16 range even at unit scale")
        return scale
    activation = 4096
    first = scale_for(tensors["transform.weight"])
    bias = [nearest(v * first) for v in tensors["bias"]]
    transform = [nearest(v * first) for v in tensors["transform.weight"]]
    # Also bound transient additions before removals in sorted reference updates:
    # at most two complete 37-feature sets can overlap during the calculation.
    accumulator_bound = max(abs(bias[j]) + 74 * max(abs(transform[i * width + j]) for i in range(780)) for j in range(width))
    if accumulator_bound >= 2**31:
        raise ValueError("Quantized accumulator bound exceeds int32")
    def dense(weight_name, bias_name, rows, cols):
        scale = scale_for(tensors[weight_name])
        while True:
            weight = [nearest(v * scale) for v in tensors[weight_name]]
            biases = [nearest(v * activation * scale) for v in tensors[bias_name]]
            bound = max(abs(biases[r]) + activation * sum(abs(v) for v in weight[r * cols:(r + 1) * cols]) for r in range(rows))
            if bound < 2**31:
                return weight, biases, scale, bound
            if scale == 1:
                raise ValueError("Quantized dense bound exceeds int32 at unit scale")
            scale //= 2
    fc1, b1, head, head_bound = dense("fc1.weight", "fc1.bias", hidden, 2 * width)
    fc2, b2, output, output_bound = dense("fc2.weight", "fc2.bias", 1, hidden)
    arrays = {"q_bias": ("std::int32_t", bias), "q_transform_weight": ("std::int16_t", transform),
              "q_fc1_weight": ("std::int16_t", fc1), "q_fc1_bias": ("std::int32_t", b1),
              "q_fc2_weight": ("std::int16_t", fc2), "q_fc2_bias": ("std::int32_t", b2)}
    return arrays, {"supported": True, "first_scale": first, "activation_scale": activation,
                    "head_weight_scale": head, "output_weight_scale": output,
                    "accumulator_abs_bound": accumulator_bound, "head_abs_bound": head_bound,
                    "output_abs_bound": output_bound, "rounding": "nearest, ties away from zero",
                    "derived_bytes": sum(len(v) * (2 if t == "std::int16_t" else 4) for t, v in arrays.values())}


def read_model(path: Path):
    data = path.read_bytes()
    if len(data) < 12 or data[:8] != b"SBNNUE1\0":
        raise ValueError("Invalid StockBear NNUE magic or truncated header")
    size, = struct.unpack_from("<I", data, 8)
    if not 0 < size <= 1 << 20 or 12 + size > len(data):
        raise ValueError("Invalid NNUE header size")
    header = json.loads(data[12:12 + size])
    payload = data[12 + size:]
    if (header["format"] != "StockBear float32 v1" or header["feature_version"] != FEATURE_VERSION or
            header["features"] != 780 or header["score_pov"] != "side_to_move" or
            header["output_cp_scale"] != 400 or header["activation"] != "clip(x,0,1)"):
        raise ValueError("Unsupported NNUE feature, activation or score convention")
    if hashlib.sha256(payload).hexdigest() != header["payload_sha256"]:
        raise ValueError("NNUE payload checksum mismatch")
    width, hidden = header["model"]["width"], header["model"]["hidden"]
    if type(width) is not int or type(hidden) is not int or not 1 <= width <= 256 or not 1 <= hidden <= 128:
        raise ValueError("Unsupported NNUE dimensions (width <=256, hidden <=128)")
    shapes = {"bias": [width], "transform.weight": [781, width],
              "fc1.weight": [hidden, 2 * width], "fc1.bias": [hidden],
              "fc2.weight": [1, hidden], "fc2.bias": [1]}
    tensors, consumed = {}, 0
    for item in header["tensors"]:
        name = item["name"]
        if name not in shapes or name in tensors or item["shape"] != shapes[name] or item["dtype"] != "<f4":
            raise ValueError("Invalid NNUE tensor names/shapes/dtypes")
        count = math.prod(shapes[name])
        if item["offset"] != consumed or consumed + count * 4 > len(payload):
            raise ValueError("Invalid NNUE tensor offsets/lengths")
        values = struct.unpack_from(f"<{count}f", payload, consumed)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Non-finite NNUE weights")
        tensors[name] = values
        consumed += count * 4
    if set(tensors) != set(shapes) or consumed != len(payload):
        raise ValueError("Missing NNUE tensors or trailing payload")
    if any(tensors["transform.weight"][780 * width:]):
        raise ValueError("NNUE padding row must be zero")
    return header, tensors, hashlib.sha256(data).hexdigest()


def generate_header(model: Path, output: Path):
    header, tensors, checksum = read_model(model)
    lines = ["// Generated by tools/embed_nnue.py; do not edit.", "#pragma once", "#include <cstdint>",
             "namespace chesslab::nnue_weights {",
             f"inline constexpr int WIDTH = {header['model']['width']};",
             f"inline constexpr int HIDDEN = {header['model']['hidden']};",
             f'inline constexpr const char* SHA256 = "{checksum}";',
             f'inline constexpr const char* NAME = {json.dumps(model.name)};']
    for name, values in tensors.items():
        lines.append(f"alignas(64) inline constexpr float {name.replace('.', '_')}[] = {{")
        for i in range(0, len(values), 8):
            lines.append("    " + ", ".join(v.hex() + "f" for v in values[i:i + 8]) + ",")
        lines.append("};")
    width, hidden = header["model"]["width"], header["model"]["hidden"]
    transposed = [tensors["fc1.weight"][h * 2 * width + j] for j in range(2 * width) for h in range(hidden)]
    lines.append("alignas(64) inline constexpr float fc1_transposed[] = {")
    for i in range(0, len(transposed), 8):
        lines.append("    " + ", ".join(v.hex() + "f" for v in transposed[i:i + 8]) + ",")
    lines.append("};")
    try:
        quantized, quantization = quantize_tensors(header, tensors)
    except (ValueError, OverflowError) as error:
        # Float32 compatibility must not depend on an optional quantization trial.
        quantization = {"supported": False, "reason": str(error), "first_scale": 1,
                        "activation_scale": 4096, "head_weight_scale": 1, "output_weight_scale": 1}
        quantized = {"q_" + n.replace(".", "_"): ("std::int16_t" if "weight" in n else "std::int32_t", [0] * len(v)) for n, v in tensors.items()}
    lines.append(f"inline constexpr bool Q_ENABLED = {'true' if quantization['supported'] else 'false'};")
    for key in ("first_scale", "activation_scale", "head_weight_scale", "output_weight_scale"):
        lines.append(f"inline constexpr int Q_{key.upper()} = {quantization[key]};")
    for name, (kind, values) in quantized.items():
        lines.append(f"alignas(64) inline constexpr {kind} {name}[] = {{")
        for i in range(0, len(values), 16):
            lines.append("    " + ", ".join(str(v) for v in values[i:i + 16]) + ",")
        lines.append("};")
    lines.append("}  // namespace chesslab::nnue_weights\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    dimensions = output.with_name("nnue_dimensions.hpp")
    dimension_text = ("// Generated model dimensions; no weights.\n#pragma once\n"
                      f"namespace chesslab {{ inline constexpr int NNUE_WIDTH = {width}; }}\n")
    if not dimensions.exists() or dimensions.read_text(encoding="utf-8") != dimension_text:
        dimensions.write_text(dimension_text, encoding="utf-8")
    contents = "\n".join(lines)
    if not output.exists() or output.read_text(encoding="utf-8") != contents:
        output.write_text(contents, encoding="utf-8")
    return {"model": str(model), "sha256": checksum, "payload_sha256": header["payload_sha256"],
            "width": header["model"]["width"], "hidden": header["model"]["hidden"],
            "feature_version": FEATURE_VERSION, "quantization": quantization}
