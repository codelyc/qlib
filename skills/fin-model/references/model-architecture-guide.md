# 模型架构设计指南

> 来源: RD-Agent `model_hypothesis_specification` 8条原则 + RAG 知识注入

---

## 领域知识（RAG — 对齐 RD-Agent model_proposal.py）

1. **时序数据**: 量化金融市场数据本质是时间序列，**GRU/LSTM 模型最适合**。不推荐 GNN（图神经网络，当前场景不适用）。
2. **数据规模**: 训练集约 **< 100万样本**，验证集约 **25万样本**。需严格控制模型大小，过大模型会严重过拟合。
3. **超参敏感性**: 超参数对训练结果影响显著。如果架构本身合理但性能差，**优先调超参而非改架构**。
4. **输入特征**: Alpha20（20维）或 Alpha158（158维），由 Qlib 自动计算，模型只需处理数值输入。

---

## 8 条假设设计原则（对齐 RD-Agent `model_hypothesis_specification`）

1. **分析实验轨迹**: 观察历史实验中模型架构的不足 — 是参数设置、架构缺陷还是缺乏创新？
2. **参考关键实验**: 重点关注 `last_hypothesis`（上一轮）和 `SOTA_hypothesis`（最佳轮），可以在其基础上优化或提出新思路。
3. **首轮从简单开始**: 如果没有先验实验，从简单小架构开始（如 2 层 MLP 或单层 GRU）。
4. **连续失败则回归简单**: 多次尝试未达 SOTA → 考虑探索全新方向，可以回到简单架构重新出发。
5. **只关注 PyTorch 架构**: 每个假设必须具体到层配置、激活函数、正则化方法和整体模型结构。**不做特征处理**。
6. **不含无关内容**: 避免输入特征、优化策略等与架构无关的内容。
7. **超参调整也是有效策略**: 架构稳定但性能差时，调整超参（lr, dropout, hidden_dim）往往更有效。
8. **追求顶会级创新**: 经过足够多轮传统模型尝试后，目标是 NeurIPS/ICLR/ICML/SIGKDD 级别的时序建模创新。

---

## 推荐架构路线图

### 阶段 1: 基线建立（第 1-2 轮）
| 模型 | 类型 | 适用场景 | 参数量 |
|------|------|---------|--------|
| SimpleMLP | Tabular | 快速基线 | ~5K |
| GRU | TimeSeries | 时序基线 | ~20K |

### 阶段 2: 经典改进（第 3-5 轮）
| 模型 | 类型 | 改进点 | 参数量 |
|------|------|--------|--------|
| LSTM | TimeSeries | 长程依赖 | ~30K |
| ALSTM | TimeSeries | LSTM + Attention | ~40K |
| TCN | TimeSeries | 因果卷积 + 并行 | ~25K |

### 阶段 3: 创新探索（第 5+ 轮）
| 模型 | 类型 | 创新点 | 参数量 |
|------|------|--------|--------|
| Transformer | TimeSeries | Multi-head Attention | ~50K |
| MLP-Mixer | Tabular | Token-mixing + Channel-mixing | ~30K |
| Hybrid | TimeSeries | GRU + Transformer | ~60K |
| 自定义 | TimeSeries | 新颖结构（追求顶会级） | 灵活 |

---

## 超参调整策略

### 训练超参（通过 .env 或 model_meta.json 控制）

| 参数 | 默认值 | 调大场景 | 调小场景 |
|------|-------|---------|---------|
| `n_epochs` | 100 | 模型大/收敛慢 | 已快速收敛 |
| `lr` | 2e-4 | Early stop 太晚 | Early stop <30轮 |
| `early_stop` | 10 | 想探索更多 | loss 震荡 |
| `batch_size` | 256 | 训练不稳定 | 想要更精细梯度 |
| `weight_decay` | 1e-4 | 过拟合 | 欠拟合 |

### 架构超参

| 参数 | 范围建议 | 说明 |
|------|---------|------|
| `hidden_dim` | 32-128 | 数据量小 → 偏小；特征多 → 偏大 |
| `num_layers` | 1-3 | 超过 3 层容易过拟合 |
| `dropout` | 0.1-0.5 | 过拟合 → 增大；欠拟合 → 减小 |
| `num_heads` (Attention) | 2-8 | 特征维度需被整除 |

---

## 常见陷阱

1. **模型过大**: 100万参数以上几乎一定过拟合，建议 <50K 参数
2. **遗忘 `model_cls`**: 文件末尾必须写 `model_cls = YourModelName`
3. **输出 shape 错误**: 必须是 `(batch, 1)` 而非 `(batch,)` 或 `(batch, num_features)`
4. **TimeSeries 模型忘记接收 `num_timesteps`**: `__init__` 签名必须包含此参数
5. **使用 Sigmoid 输出**: 回归任务不应限制输出范围，直接用 `nn.Linear` 输出
6. **硬编码维度**: 所有维度必须通过参数传入（`num_features`, `num_timesteps`）
