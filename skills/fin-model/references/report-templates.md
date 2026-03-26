# 报告模板

> Agent 在每轮结束时需要写的报告文件和追加到 summary 的内容。

---

## 1. 单轮报告 ($ROUND_DIR/report.md)

```markdown
# 第 N 轮模型优化报告

## 假设
- **陈述**: [精确假设]
- **理由**: [提出理由]
- **验证结果**: ✅ 成功 / ❌ 失败 / ⚠️ 部分

## 模型规格
- **名称**: [模型名]
- **类型**: TimeSeries / Tabular
- **架构**: [逐层描述]
- **参数量**: [N]

## 训练超参
| 参数 | 值 |
|------|-----|
| n_epochs | 100 |
| lr | 2e-4 |
| early_stop | 10 |
| batch_size | 256 |
| weight_decay | 1e-4 |

## 回测结果
[analysis.json 内容的人类可读版]

## 训练日志分析
[training_analysis 的要点]

## 反馈与决策
[结构化反馈]

## 下一步
[Agent 建议的方向]
```

---

## 2. 累积摘要 ($EXP_ROOT/summary.md)

每轮追加：

```markdown
---
### 第 N 轮: [模型名] ([日期])
- **假设**: [一句话]
- **结果**: IC=[值], 年化=[值]%, 夏普=[值]
- **vs SOTA**: [改善/下降 情况]
- **决策**: ✅ 更新SOTA / ❌ 不更新
- **下一步**: [方向]
```

---

## 3. 挑战提取 ($ROUND_DIR/challenges.json)

第 2 轮起，分析上一轮的挑战：

```json
{
  "challenges": [
    {
      "id": "C1",
      "type": "overfitting",
      "description": "valid loss 在第 20 轮开始上升，模型严重过拟合",
      "severity": "high",
      "suggested_mitigation": "增大 dropout 到 0.5 或增大 weight_decay 到 1e-3"
    },
    {
      "id": "C2",
      "type": "architecture",
      "description": "GRU 单向结构无法捕捉未来依赖信号",
      "severity": "medium",
      "suggested_mitigation": "改用双向 LSTM 或 Transformer"
    }
  ]
}
```

**挑战类型**:
- `overfitting` — 过拟合
- `underfitting` — 欠拟合
- `architecture` — 架构局限
- `hyperparameter` — 超参不当
- `convergence` — 收敛问题
- `efficiency` — 效率问题
