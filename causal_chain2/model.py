"""轻量 GCN：图级因果链分类 + 可选边类型辅助头。"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F


class LiteGCN(nn.Module):
    def __init__(
        self,
        in_dim: int,
        hidden: int,
        num_classes: int,
        num_layers: int = 2,
    ) -> None:
        super().__init__()
        self.num_layers = num_layers
        self.in_lin = nn.Linear(in_dim, hidden)
        self.layers = nn.ModuleList(
            [nn.Linear(hidden, hidden) for _ in range(num_layers)]
        )
        self.head = nn.Linear(hidden, num_classes)
        self.edge_head = nn.Linear(2 * hidden, 1)

    def _aggregate(self, x: torch.Tensor, edge_index: torch.Tensor, n: int) -> torch.Tensor:
        row, col = edge_index[0], edge_index[1]
        agg = torch.zeros(n, x.size(1), device=x.device, dtype=x.dtype)
        agg.index_add_(0, col, x[row])
        deg = torch.bincount(col, minlength=n).float().unsqueeze(-1).clamp(min=1.0)
        return agg / deg

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        n = x.size(0)
        h = F.relu(self.in_lin(x))
        for lin in self.layers:
            h = self._aggregate(h, edge_index, n)
            h = F.relu(lin(h))
        logits = self.head(h.mean(dim=0, keepdim=True))
        return logits, h

    def edge_logits(self, h: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        row, col = edge_index[0], edge_index[1]
        pair = torch.cat([h[row], h[col]], dim=-1)
        return self.edge_head(pair).squeeze(-1)
