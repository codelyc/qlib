# 回测指标解读指南

> 来源: RD-Agent `feedback.py` IMPORTANT_METRICS + Qlib 文档

---

## 核心指标（对齐 RD-Agent）

| 指标 | 全称 | 含义 | 好的范围 | 权重 |
|------|------|------|---------|------|
| **IC** | Information Coefficient | 预测值与实际收益的相关系数 | >0.03 | 20% |
| **ICIR** | IC Information Ratio | IC均值/IC标准差，衡量预测稳定性 | >0.3 | 10% |
| **Rank IC** | Rank Information Coefficient | 排名相关系数，更鲁棒 | >0.03 | 20% |
| **Rank ICIR** | Rank IC Information Ratio | Rank IC 的稳定性 | >0.3 | 10% |
| **年化收益** | Annualized Return (excess, with cost) | 扣除成本后超额年化收益 | >0% | 25% |
| **最大回撤** | Max Drawdown (excess, with cost) | 最大亏损幅度（负数） | >-20% | 0% |
| **夏普比率** | Information Ratio | 收益/风险比 | >1.0 | 15% |

---

## 指标解读

### IC / ICIR
- IC 衡量模型预测能力的强度
- ICIR 衡量预测的稳定性（IC 的夏普比率）
- **IC > 0.05** 是很好的模型
- **ICIR > 0.5** 表示预测非常稳定

### 年化收益 (Annualized Return)
- 超额收益 = 策略收益 - 基准收益
- 已扣除交易成本（买入万五 + 卖出万十五）
- **正值** = 跑赢基准（CSI300）

### 最大回撤 (Max Drawdown)
- 从峰值到谷值的最大亏损
- **-10%** 是可接受的回撤
- **-20%** 需要关注
- 值越接近 0 越好（注意是负数）

### 夏普比率 (Information Ratio)
- 超额收益 / 超额收益的标准差
- **>1.0** 风险调整后收益良好
- **>2.0** 优秀

---

## SOTA 更新决策权重

综合评分 = Σ(权重 × 归一化改善值)

```
IC:       20%
Rank IC:  20%
年化收益:  25% (最高权重 — 对齐 RD-Agent "年化收益改善即推荐替换")
夏普比率:  15%
ICIR:     10%
Rank ICIR: 10%
```

**更新条件**: 综合评分 > 0 **且** 至少 2 项指标改善

---

## 训练日志诊断

| 现象 | 诊断 | 建议 |
|------|------|------|
| Early stop < 30 轮 | lr 过高或模型不稳定 | 降低 lr (1e-4 → 5e-5) |
| Early stop = n_epochs | 模型未收敛 | 增大 n_epochs 或降低 lr |
| valid loss 上升 | 过拟合 | 增大 dropout/weight_decay |
| train loss 不降 | 欠拟合 | 增大模型/增大 lr |
| 训练 > 10 分钟 | 模型过大 | 减小 hidden_dim/layers |
