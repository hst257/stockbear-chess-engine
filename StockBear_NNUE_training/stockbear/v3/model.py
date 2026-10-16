from __future__ import annotations

import torch
from torch import nn

from .features import feature_count


class KingRelativeNNUE(nn.Module):
    def __init__(self, king_buckets: int = 64):
        super().__init__()
        self.king_buckets = king_buckets
        padding = feature_count(king_buckets)
        self.transform = nn.EmbeddingBag(padding + 1, 32, mode="sum", padding_idx=padding)
        self.bias = nn.Parameter(torch.zeros(32))
        self.fc1 = nn.Linear(64, 16)
        self.fc2 = nn.Linear(16, 1)
        nn.init.normal_(self.transform.weight, std=0.025)
        with torch.no_grad():
            self.transform.weight[padding].zero_()

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        batch = features.shape[0]
        sums = self.transform(features.reshape(batch * 2, -1)) + self.bias
        hidden = self.fc1(sums.clamp(0, 1).reshape(batch, 64)).clamp(0, 1)
        return self.fc2(hidden).squeeze(-1)
