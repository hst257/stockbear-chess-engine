from __future__ import annotations

import torch
from torch import nn

from .features import FEATURES, PADDING


class NNUE(nn.Module):
    def __init__(self, width: int = 128, hidden: int = 32):
        super().__init__()
        self.width, self.hidden = width, hidden
        # Active row lookup/sum: no dense one-hot board tensor. Dense gradients let
        # AdamW apply consistent weight decay to this small feature table.
        self.transform = nn.EmbeddingBag(FEATURES + 1, width, mode="sum", padding_idx=PADDING)
        self.bias = nn.Parameter(torch.zeros(width))
        self.fc1 = nn.Linear(2 * width, hidden)
        self.fc2 = nn.Linear(hidden, 1)
        nn.init.normal_(self.transform.weight, std=0.025)
        with torch.no_grad():
            self.transform.weight[PADDING].zero_()

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        batch = features.shape[0]
        accumulators = self.transform(features.reshape(batch * 2, -1)) + self.bias
        activated = accumulators.clamp(0, 1).reshape(batch, self.width * 2)
        hidden = self.fc1(activated).clamp(0, 1)
        return self.fc2(hidden).squeeze(-1)  # centipawns / 400
