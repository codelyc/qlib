# Bandit Action Advisor 使用指南

## 概述

Bandit 是基于 **Thompson Sampling** 的行动建议器，参考 [RD-Agent](../../../RD-Agent/rdagent/scenarios/qlib/proposal/bandit.py) 的 `LinearThompsonTwoArm`。

**核心思想**: 把"做因子"和"做模型"看作 Bandit 问题的两个臂（arm），根据历史回报动态调整建议。

**重要**: Bandit 只给**建议**，最终决策权在用户手中。

## 工作原理

### 8 维指标向量

每轮实验产出 8 个指标，组成向量:

| 维度 | 指标 | 权重 | 含义 |
|------|------|------|------|
| 0 | IC | 0.10 | Information Coefficient |
| 1 | ICIR | 0.10 | IC Information Ratio |
| 2 | Rank IC | 0.05 | Rank Information Coefficient |
| 3 | Rank ICIR | 0.05 | Rank ICIR |
| 4 | ARR | **0.25** | 年化收益率（最高权重） |
| 5 | IR | 0.15 | Information Ratio |
| 6 | -MDD | 0.10 | 最大回撤（取负，越小越好） |
| 7 | Sharpe | **0.20** | 夏普比率（第二权重） |

### Thompson Sampling 流程

```
1. 每轮结束，记录 (action, 8维指标, 加权奖励) 到 Bandit
2. Bandit 维护两个后验分布: P(factor) 和 P(model)
3. 下一轮: 从两个分布各采样一次
4. 谁的采样值高 → 建议做谁
5. 随着数据积累，后验逐渐收敛 → 建议越来越准
```

### 冷启动策略

| 轮次 | 建议 | 原因 |
|------|------|------|
| 第 1-2 轮 | 固定 factor | 需要先积累因子基线 |
| 第 3 轮 | 固定 model（如果还没做过） | 需要模型基线 |
| 第 4+ 轮 | Bandit 动态建议 | 数据够了 |

## 命令行用法

### 获取建议

```bash
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py suggest \
    --exp-root $QUANT_EXP_ROOT
```

输出示例:
```json
{
  "action": "model",
  "scores": {"factor": 0.31, "model": 0.72},
  "reason": "Bandit 采样: 模型(0.72) > 因子(0.31)，建议切换到模型优化",
  "factor_count": 3,
  "model_count": 1
}
```

### 记录结果

```bash
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py record \
    --exp-root $QUANT_EXP_ROOT \
    --round 3 --action factor \
    --metrics '{"ic":0.04,"icir":0.45,"rank_ic":0.03,"rank_icir":0.4,"arr":0.08,"ir":1.5,"mdd":0.15,"sharpe":1.2}'
```

## Agent 如何使用

1. **每轮开始前**: 调用 `suggest` 获取建议
2. **展示给用户**: "Bandit 建议这轮做[factor/model]，理由是..."
3. **用户决定**: 用户可以采纳或忽略建议
4. **轮次结束后**: `update_quant_sota.py` 会自动更新 trace 中的指标

## 数据存储

Bandit 状态持久化在 `$QUANT_EXP_ROOT/quant_trace.json` 的 `bandit_state` 字段中。

## 参考

- RD-Agent 原始实现: `rdagent/scenarios/qlib/proposal/bandit.py`
- 论文: Thompson Sampling for Contextual Bandits
