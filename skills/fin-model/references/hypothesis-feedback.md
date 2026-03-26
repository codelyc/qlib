# 假设-反馈循环规范

> 来源: RD-Agent `prompts.yaml` — `model_hypothesis_specification` + `model_feedback_generation` + `model_experiment_output_format`

---

## 1. 假设输出格式

Agent 在每轮开头生成假设，必须遵循此 JSON 格式：

```json
{
  "hypothesis": "精确、可测试、创新的陈述。2-3 句话，明确指定架构方法和预期改进。",
  "reason": "基于证据的逻辑解释（实验轨迹、领域知识）。≤2 句。"
}
```

**示例**:
```json
{
  "hypothesis": "使用双向 LSTM 替代单向 GRU，通过双向时序信息捕捉提升预测精度。在 LSTM 输出上增加 Self-Attention 层，让模型自动关注关键时间步。",
  "reason": "上轮 GRU 在 IC 指标上为 0.041，训练日志显示 loss 未充分收敛。双向结构 + Attention 在时序预测文献中被证明有效。"
}
```

---

## 2. 模型 Specification 输出格式

假设确认后，Agent 设计具体模型规格，遵循此 JSON 格式（对齐 RD-Agent `model_experiment_output_format`）：

**⚠️ 每轮只设计一个模型！**

```json
{
  "模型名称": {
    "description": "模型的详细描述",
    "formulation": "LaTeX 数学公式",
    "architecture": "逐层架构描述（神经网络层、激活函数、正则化）",
    "variables": {
      "\\hat{y}": "股票预测收益率",
      "h_t": "时间步 t 的隐藏状态"
    },
    "hyperparameters": {
      "hidden_dim": 64,
      "num_layers": 2,
      "dropout": 0.3,
      "num_heads": 4
    },
    "training_hyperparameters": {
      "n_epochs": 100,
      "lr": 0.0002,
      "early_stop": 10,
      "batch_size": 256,
      "weight_decay": 0.0001
    },
    "model_type": "TimeSeries"
  }
}
```

`model_type` 只能是 `"Tabular"` 或 `"TimeSeries"`。

---

## 3. 反馈分析格式

回测完成后，Agent 分析结果并生成结构化反馈（对齐 RD-Agent `model_feedback_generation`）：

```json
{
  "Observations": "先分析训练日志（超参是否有问题），然后精确总结当前指标和 SOTA 指标的对比。≤3 句，数据驱动。",
  "Feedback for Hypothesis": "明确基于数据确认或反驳假设。≤2 句。",
  "New Hypothesis": "修正后的假设，考虑观察到的模式和当前假设的局限性。≤2 句。",
  "Reasoning": "解释新假设的理由，使用具体趋势或性能变化。≤2 句。",
  "Decision": true
}
```

**Decision 判断标准**（对齐 RD-Agent feedback.py）:
1. **年化收益改善 → true**: 推荐替换 SOTA（小改善也算）
2. **其他指标小幅波动可接受**: 只要年化收益改善，其他指标略微下降不阻塞
3. **结果显著差于 SOTA → false + 建议换方向**: 考虑全新架构

**首轮特殊规则**: 无 SOTA 可比时，只要 ICIR > 0（性能不太差）就视为成功，不设过高门槛。

---

## 4. SOTA 决策树

```
开始
├── 首轮（无 SOTA）?
│   ├── ICIR > 0 → ✅ 接受为 SOTA
│   └── ICIR ≤ 0 → ❌ 拒绝，模型有严重问题
│
├── 年化收益改善?
│   ├── 是 → ✅ 替换 SOTA（即使其他指标略降）
│   └── 否 → 继续检查
│       ├── IC + 夏普 都改善? → ✅ 替换
│       └── 多项指标恶化 → ❌ 不替换
│           ├── 差距小 → 建议微调超参
│           └── 差距大 → 建议换架构方向
```

---

## 5. 展示给用户的报告模板

Agent 在每轮结束时展示（必须包含所有部分）：

```markdown
## 📊 第 N 轮模型优化结果

### 假设验证: ✅/❌/⚠️

**假设**: [本轮假设]
**验证结果**: [基于数据的确认/反驳]

### 指标对比

| 指标 | 本轮 | SOTA | 变化 | 判断 |
|------|------|------|------|------|
| IC | 0.0521 | 0.0489 | +0.0032 | ✅ |
| 年化收益 | 8.23% | 7.15% | +1.08% | ✅ |
| 最大回撤 | -12.5% | -11.2% | -1.3% | ❌ |
| 夏普比率 | 1.42 | 1.35 | +0.07 | ✅ |

### 🔍 训练日志分析

- **Early Stopping**: 第 67/100 轮停止
- **Loss 趋势**: train 0.0023→0.0019, valid 0.0025→0.0021（正常下降）
- **过拟合**: 未检测到（valid loss 持续下降）
- **训练时间**: 3分42秒

### 💡 反馈
[结构化反馈 JSON 的人类可读版本]

### 🎯 下一步建议

1. **深化** (推荐): 在当前架构上增加 Dropout 降低回撤
2. **换方向**: 尝试 Transformer 架构
3. **微调**: 仅调整 lr=1e-4, weight_decay=5e-4
4. **停止**: 当前结果已满意

请选择下一步方向？
```
