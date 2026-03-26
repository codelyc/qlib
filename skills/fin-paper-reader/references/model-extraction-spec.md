# 模型提取规范

> 来源：RD-Agent `model_experiment_output_format` + `model_hypothesis_specification`，对齐 `fin-model` 阶段 1 的 Specification 格式。

---

## 输出格式（与 fin-model 完全兼容）

从论文中提取的每个模型，必须输出为以下 JSON 格式：

```json
{
    "model_name": {
        "description": "模型的详细描述",
        "formulation": "核心数学公式（LaTeX）",
        "architecture": "逐层架构描述",
        "variables": {
            "\\hat{y}": "预测的收益率",
            "variable_2": "变量描述"
        },
        "hyperparameters": {
            "hidden_dim": "64",
            "num_layers": "2",
            "dropout": "0.1"
        },
        "training_hyperparameters": {
            "n_epochs": "100",
            "lr": "1e-3",
            "early_stop": "10",
            "batch_size": "256",
            "weight_decay": "1e-4"
        },
        "model_type": "TimeSeries"
    }
}
```

### 字段说明

| 字段 | 要求 | 示例 |
|------|------|------|
| `model_name` | 英文，简洁 | `ALSTM`, `TCN_Attention` |
| `description` | 包含模型目标和创新点 | `LSTM with temporal attention for stock return prediction` |
| `formulation` | 核心计算公式 LaTeX | `h_t = \sigma(W_h h_{t-1} + W_x x_t + b)` |
| `architecture` | 逐层描述（输入→隐藏→输出） | 见下文 |
| `variables` | 公式中所有变量的含义 | `{"h_t": "hidden state at time t"}` |
| `hyperparameters` | 架构超参 | `{"hidden_dim": "64"}` |
| `training_hyperparameters` | 训练超参 | `{"lr": "1e-3"}` |
| `model_type` | `Tabular` 或 `TimeSeries` | `TimeSeries` |

---

## 架构描述规范

`architecture` 字段必须逐层描述，让 Agent 能据此直接写 PyTorch 代码：

### TimeSeries 模型示例

```
Input: (batch_size, num_timesteps, num_features)
→ Layer 1: GRU(input_size=num_features, hidden_size=64, num_layers=2, batch_first=True, dropout=0.1)
→ Layer 2: Temporal Attention(hidden_size=64)
  - Query: last hidden state h_T
  - Key/Value: all hidden states [h_1, ..., h_T]
  - Attention weights: softmax(h_T · H^T / sqrt(d))
  - Context: weighted sum of hidden states
→ Layer 3: Linear(64, 1)
Output: (batch_size, 1)
```

### Tabular 模型示例

```
Input: (batch_size, num_features)
→ Layer 1: Linear(num_features, 128) + BatchNorm + ReLU + Dropout(0.3)
→ Layer 2: Linear(128, 64) + BatchNorm + ReLU + Dropout(0.3)
→ Layer 3: Linear(64, 1)
Output: (batch_size, 1)
```

---

## 模型类型判断

| 论文特征 | model_type | 依据 |
|---------|-----------|------|
| 使用 RNN/LSTM/GRU/Transformer | `TimeSeries` | 显式处理时序 |
| 输入含时间窗口 (lookback window) | `TimeSeries` | 需要历史序列 |
| 使用 Attention 处理时序依赖 | `TimeSeries` | 时序注意力 |
| 纯全连接/树模型 | `Tabular` | 截面特征 |
| 输入为单时间步特征向量 | `Tabular` | 无时序结构 |
| MLP-Mixer / TabNet | `Tabular` | 表格数据专用 |

---

## Qlib 约束（提取时必须考虑）

从论文中提取模型时，必须适配 Qlib GeneralPTNN 框架的约束：

### 代码签名约束

```python
class ModelName(nn.Module):
    def __init__(self, num_features, num_timesteps=None):
        """
        num_features: 输入特征维度（Alpha20=20, Alpha158=158, 自定义因子=158+N）
        num_timesteps: 时序窗口长度（TimeSeries 模型必须使用，Tabular 模型忽略）
        """
        super().__init__()
        ...

    def forward(self, x):
        """
        x: (batch_size, num_features)        — Tabular
        x: (batch_size, num_timesteps, num_features) — TimeSeries
        return: (batch_size, 1)              — 必须！
        """
        ...

model_cls = ModelName  # 文件末尾必须有这一行
```

### 不允许的操作

| 操作 | 原因 |
|------|------|
| 自定义训练循环 | Qlib 框架负责训练 |
| import qlib | 模型代码独立于框架 |
| 特征预处理 | 输入已经是标准化特征 |
| 自定义 loss | Qlib 使用 MSELoss |
| 多任务输出 | 必须是 (batch, 1) |

### 参数量控制

| 范围 | 建议 |
|------|------|
| < 10K | ✅ 适合首轮基线 |
| 10K-50K | ✅ 经典模型 |
| 50K-100K | ⚠️ 需要正则化 |
| > 100K | ❌ 几乎一定过拟合 |

---

## 提取难度评估

| 难度 | 标准 | 示例 |
|------|------|------|
| 🟢 低 | 标准架构，PyTorch 直接有 | MLP, LSTM, GRU |
| 🟡 中 | 需要自定义 Module 但逻辑清晰 | ALSTM, TCN, Transformer |
| 🔴 高 | 复杂的自定义操作或论文描述不清 | 图神经网络、强化学习 |

---

## 超参数映射

论文中的超参需映射到 Qlib 的配置体系：

| 论文超参 | Qlib 对应 | 默认值 | 说明 |
|---------|-----------|--------|------|
| learning rate | `lr` | 2e-4 | `.env` 中配置 |
| epochs | `n_epochs` | 100 | `.env` 中配置 |
| batch size | `batch_size` | 256 | `.env` 中配置 |
| early stopping patience | `early_stop` | 10 | `.env` 中配置 |
| weight decay / L2 | `weight_decay` | 1e-4 | `.env` 中配置 |
| lookback window | `num_timesteps` | 20 | TimeSeries 专用 |
| hidden dimension | 代码内设置 | 64 | model.py 内 |
| number of layers | 代码内设置 | 2 | model.py 内 |
| dropout rate | 代码内设置 | 0.1 | model.py 内 |

> ⚠️ **论文中的超参仅供参考**。实际训练数据规模（~100万样本）可能与论文不同，需要根据 Qlib 场景调整。

---

## 模型假设生成

提取完模型 Specification 后，Agent 必须生成假设文本衔接 `fin-model`：

```json
{
    "hypothesis": "基于论文《XX》提出的 XX 架构，该模型通过 XX 机制捕捉时序依赖，预期在 Qlib 上比 GRU baseline 有更好的 ICIR。",
    "reason": "论文在 XX 数据集上验证了该架构的有效性。核心创新是 XX。",
    "source": "论文标题",
    "extracted_models": ["model_name"]
}
```

---

## 与 fin-model Specification 格式对照

| 字段 | fin-paper-reader 输出 | fin-model 阶段 1 需要 | 兼容？ |
|------|---------------------|---------------------|--------|
| model_name | ✅ | ✅ | ✅ |
| description | ✅ | ✅ | ✅ |
| formulation | ✅ LaTeX | ✅ LaTeX | ✅ |
| architecture | ✅ 逐层描述 | ✅ 逐层描述 | ✅ |
| variables | ✅ | ✅ | ✅ |
| hyperparameters | ✅ | ✅ | ✅ |
| training_hyperparameters | ✅ | ✅ | ✅ |
| model_type | ✅ Tabular/TimeSeries | ✅ | ✅ |

> **结论**：`fin-paper-reader` 的输出可以**无缝**作为 `fin-model` 阶段 1 的输入。
