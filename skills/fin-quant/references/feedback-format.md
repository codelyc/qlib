# 结构化反馈格式 (Structured Feedback Format)

> 参考: RD-Agent `feedback.py` 的 `HypothesisFeedback` + `prompts.yaml` 的 `factor_feedback_generation` / `model_feedback_generation`

## 概述

**每轮结束后，Agent 必须生成结构化 JSON 反馈**，写入 `quant_trace.json`。
这不是可选的——结构化反馈是 CoSTEER 知识回溯的核心，下一轮 Agent 读取历史时依赖这些字段做决策。

---

## 反馈 JSON 格式

```json
{
  "observations": "本轮观察到的现象（指标变化、异常行为）",
  "hypothesis_evaluation": "假设是否得到验证？支持还是反驳？",
  "new_hypothesis": "基于本轮结果，下一步应该尝试什么？",
  "reasoning": "推理链：为什么建议这个方向？",
  "replace_sota": true
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `observations` | string | ✅ | 客观描述：指标对比（IC/Sharpe/ARR 变化）、训练日志关键信息 |
| `hypothesis_evaluation` | string | ✅ | 判断本轮假设是否成立。如"动量因子假设得到验证，IC=0.04 > 基线" |
| `new_hypothesis` | string | ✅ | 下一步建议。如"建议尝试多窗口动量组合"或"建议切换到模型优化" |
| `reasoning` | string | ✅ | 推理链。如"IC 已提升但换手率偏高，加平滑可能降低成本" |
| `replace_sota` | bool | ✅ | 是否应成为新 SOTA？任何指标小幅提升都应考虑 yes |

---

## 因子轮反馈指南

评估因子时关注：

1. **IC / Rank IC** — 预测能力的核心指标
2. **年化收益 (ARR)** — 最重要的财务指标（权重 0.25）
3. **夏普比率** — 风险调整后收益（权重 0.20）
4. **最大回撤 (MDD)** — 下行风险控制

**SOTA 判定原则**（参考 RD-Agent `factor_feedback_generation`）：
- 任何小幅改进都应考虑纳入 SOTA（设 `replace_sota: true`）
- 如果年化收益有提升，即使其他指标略有波动也可接受
- 持续积累因子是目标——不要因为单指标下降就拒绝

**反馈示例**（因子轮）：
```json
{
  "observations": "IC 从 0.030 提升到 0.042（+40%），年化收益从 5.9% 升至 7.8%。但 MDD 从 -4.6% 扩大到 -6.2%。单因子 IC: vol_rebound=0.038, trend_break=0.028",
  "hypothesis_evaluation": "放量反弹因子假设验证成功——大跌后放量确实有预测价值",
  "new_hypothesis": "建议下一轮: (1) 对 vol_rebound 加 20 日指数平滑降低换手; (2) 尝试 VIX 类波动率因子捕捉恐慌情绪",
  "reasoning": "MDD 扩大主要因为因子信号太尖锐（无平滑），加平滑后风险收益比应改善。波动率因子与现有动量/量价因子正交度高，有望增加信息增量",
  "replace_sota": true
}
```

---

## 模型轮反馈指南

评估模型时关注：

1. **训练日志** — Early Stopping 轮次、Loss 趋势、过拟合检测
2. **IC / ICIR** — 模型预测能力
3. **年化收益** — 实际交易效果
4. **参数量** — 模型复杂度是否合理

**反馈示例**（模型轮）：
```json
{
  "observations": "GRU_v2 在 epoch 67 early stop，valid loss 0.0042 → 训练充分。IC=0.015（vs SOTA 0.012），年化 8.2%（vs 6.7%）。参数量 85k，推理延迟 <1ms",
  "hypothesis_evaluation": "双层 GRU + Dropout=0.2 假设验证——深层表示学习有效，Dropout 控制了过拟合",
  "new_hypothesis": "建议: (1) 尝试 ALSTM（注意力+LSTM）捕捉时间步权重; (2) 或切回因子轮——当前 IC=0.015 已不错，因子增量可能收益更高",
  "reasoning": "模型 IC 已从 0.012 提升到 0.015（+25%），继续在模型上的边际收益递减。Bandit 建议切因子（factor=0.72 > model=0.31），与直觉一致",
  "replace_sota": true
}
```

---

## concise_knowledge 字段

**每轮结束时，Agent 还须提炼 1-2 句核心洞察**，通过 `--concise-knowledge` 写入 trace。

这些知识会在下一轮的 LLM context 中展示，实现持续学习。

**好的 concise_knowledge**：
- "5日动量因子 IC=0.04 稳定，但换手高——需加指数平滑"
- "GRU hidden_dim=256 过大导致过拟合，128 更合适"
- "量价因子与趋势因子 IC 相关性 0.85——未来避免同维度"

**不好的 concise_knowledge**（太笼统）：
- "这轮还行"
- "模型需要改进"

---

## 工作流集成

```bash
# 回测完成后，Agent 调用:
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/quant_trace.py record \
    --exp-root $QUANT_EXP_ROOT \
    --round $ROUND \
    --action $ACTION \
    --task "放量反弹因子" \
    --code-path "round_1/vol_rebound/factor.py" \
    --result success \
    --is-sota \
    --metrics '{"ic":0.042,"icir":0.55,"arr":0.078,"sharpe":1.35}' \
    --feedback '{"observations":"IC +40%, ARR +32%","hypothesis_evaluation":"放量反弹假设验证","new_hypothesis":"加平滑+尝试波动率因子","reasoning":"信号太尖锐致MDD扩大","replace_sota":true}' \
    --concise-knowledge "放量反弹因子IC稳定但需平滑；波动率维度尚未探索"
```
