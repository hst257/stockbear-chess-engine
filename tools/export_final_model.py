"""Re-export the preserved final checkpoint without training or opening datasets."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'StockBear_NNUE_training'))

def export(output: Path) -> dict:
    import numpy as np
    import torch
    from stockbear.scaling_train import load_model
    checkpoint = ROOT / 'models/nnue/best.pt'
    state = torch.load(checkpoint, map_location='cpu', weights_only=False)
    model = load_model(state)
    model.eval()
    tensors, payload = ([], bytearray())
    for name, tensor in model.state_dict().items():
        array = np.ascontiguousarray(tensor.detach().numpy(), dtype='<f4')
        tensors.append(dict(name=name, shape=list(array.shape), dtype='<f4', offset=len(payload)))
        payload.extend(array.tobytes())
    header = dict(format='StockBear float32 v1', feature_version='dual-perspective-12x64-castling-ep-v1', features=780, model=dict(width=64, hidden=32), score_pov='side_to_move', output_cp_scale=400, activation='clip(x,0,1)', tensors=tensors, payload_sha256=hashlib.sha256(payload).hexdigest(), best_epoch=state['epoch'] + 1, source_checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(), experiment='scaling-experiment-20261016')
    encoded = json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    data = b'SBNNUE1\x00' + struct.pack('<I', len(encoded)) + encoded + payload
    digest = hashlib.sha256(data).hexdigest()
    if digest != 'a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3':
        raise ValueError('Checkpoint export no longer matches frozen final model')
    if output.exists() and output.read_bytes() != data:
        raise ValueError('Refusing to overwrite a different file')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return dict(path=str(output), sha256=digest, bytes=len(data), trained=False, dataset_opened=False)
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.output)), flush=True)
