# 模型示例代码

> 4 个完整可运行的 model.py 示例，从简单到复杂。每个都可直接用于 Qlib 回测。

---

## 1. SimpleMLP (Tabular)

```python
"""简单 3 层全连接网络 — Tabular 基线模型"""
import torch
import torch.nn as nn


class SimpleMLP(nn.Module):
    def __init__(self, num_features: int, num_timesteps: int = None):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(num_features, 128),
            nn.BatchNorm1d(128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 64),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(64, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, num_features)
        return self.net(x)  # (batch_size, 1)


model_cls = SimpleMLP
```

**配置**: `dataset_cls=DatasetH`, `model_type=Tabular`
**参数量**: ~10K (num_features=20)

---

## 2. GRUModel (TimeSeries)

```python
"""2 层 GRU — TimeSeries 基线模型"""
import torch
import torch.nn as nn


class GRUModel(nn.Module):
    def __init__(self, num_features: int, num_timesteps: int = 20):
        super().__init__()
        self.hidden_dim = 64
        self.num_layers = 2

        self.gru = nn.GRU(
            input_size=num_features,
            hidden_size=self.hidden_dim,
            num_layers=self.num_layers,
            batch_first=True,
            dropout=0.3,
        )
        self.fc = nn.Linear(self.hidden_dim, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, num_timesteps, num_features)
        out, _ = self.gru(x)
        # 取最后一个时间步的隐藏状态
        last_hidden = out[:, -1, :]  # (batch_size, hidden_dim)
        return self.fc(last_hidden)  # (batch_size, 1)


model_cls = GRUModel
```

**配置**: `dataset_cls=TSDatasetH`, `model_type=TimeSeries`
**参数量**: ~25K

---

## 3. LSTMAttention (TimeSeries)

```python
"""LSTM + Self-Attention — 捕捉关键时间步"""
import torch
import torch.nn as nn
import torch.nn.functional as F


class LSTMAttention(nn.Module):
    def __init__(self, num_features: int, num_timesteps: int = 20):
        super().__init__()
        self.hidden_dim = 64

        self.lstm = nn.LSTM(
            input_size=num_features,
            hidden_size=self.hidden_dim,
            num_layers=2,
            batch_first=True,
            dropout=0.3,
        )

        # Attention 层
        self.attn_fc = nn.Linear(self.hidden_dim, 1)

        # 输出层
        self.fc = nn.Sequential(
            nn.Linear(self.hidden_dim, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, num_timesteps, num_features)
        lstm_out, _ = self.lstm(x)  # (batch, timesteps, hidden)

        # Self-Attention: 对时间步加权
        attn_scores = self.attn_fc(lstm_out).squeeze(-1)  # (batch, timesteps)
        attn_weights = F.softmax(attn_scores, dim=1)      # (batch, timesteps)
        context = torch.bmm(
            attn_weights.unsqueeze(1), lstm_out
        ).squeeze(1)  # (batch, hidden)

        return self.fc(context)  # (batch, 1)


model_cls = LSTMAttention
```

**配置**: `dataset_cls=TSDatasetH`, `model_type=TimeSeries`
**参数量**: ~40K

---

## 4. TransformerModel (TimeSeries)

```python
"""Transformer Encoder — 多头注意力时序建模"""
import math

import torch
import torch.nn as nn


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 100):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )
        pe[:, 0::2] = torch.sin(position * div_term)
        if d_model > 1:
            pe[:, 1::2] = torch.cos(position * div_term[:d_model // 2])
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[:, : x.size(1), :]


class TransformerModel(nn.Module):
    def __init__(self, num_features: int, num_timesteps: int = 20):
        super().__init__()
        self.d_model = 64
        self.nhead = 4
        self.num_layers = 2

        # 输入映射到 d_model 维度
        self.input_proj = nn.Linear(num_features, self.d_model)
        self.pos_enc = PositionalEncoding(self.d_model, max_len=num_timesteps + 10)

        # Transformer Encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=self.d_model,
            nhead=self.nhead,
            dim_feedforward=128,
            dropout=0.3,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=self.num_layers
        )

        # 输出层
        self.fc = nn.Sequential(
            nn.Linear(self.d_model, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch_size, num_timesteps, num_features)
        x = self.input_proj(x)       # (batch, timesteps, d_model)
        x = self.pos_enc(x)          # 加位置编码
        x = self.transformer(x)      # (batch, timesteps, d_model)
        x = x[:, -1, :]              # 取最后时间步
        return self.fc(x)            # (batch, 1)


model_cls = TransformerModel
```

**配置**: `dataset_cls=TSDatasetH`, `model_type=TimeSeries`
**参数量**: ~50K
