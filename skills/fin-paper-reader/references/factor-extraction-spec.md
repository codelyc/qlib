# 因子提取规范

> 来源：RD-Agent `factor_experiment_output_format` + `factor_hypothesis_specification`，对齐 `fin-factor` 第 1.5 步 Specification 格式。

---

## 输出格式（与 fin-factor 完全兼容）

从论文中提取的每个因子，必须输出为以下 JSON 格式：

```json
{
    "factor_name": {
        "description": "[因子类型] 因子描述",
        "formulation": "LaTeX 公式",
        "variables": {
            "变量名1": "含义说明",
            "变量名2": "含义说明"
        }
    }
}
```

### 字段说明

| 字段 | 要求 | 示例 |
|------|------|------|
| `factor_name` | 英文，下划线连接，无空格 | `vol_weighted_momentum_5d` |
| `description` | 以 `[类型标签]` 开头 | `[动量因子] 成交量加权的5日动量` |
| `formulation` | LaTeX 格式，变量名下划线连接 | `F = \frac{\sum_{i=1}^{5} V_i \cdot R_i}{\sum_{i=1}^{5} V_i}` |
| `variables` | 每个变量/函数都有英文说明 | `{"V_i": "Day i volume", "R_i": "Day i return"}` |

### 因子类型标签

根据论文内容使用对应标签：

| 标签 | 适用 |
|------|------|
| `[动量因子]` / `[Momentum Factor]` | 价格趋势、收益率相关 |
| `[反转因子]` / `[Reversal Factor]` | 均值回归、超跌反弹 |
| `[量价因子]` / `[Volume-Price Factor]` | 成交量与价格的交互 |
| `[波动率因子]` / `[Volatility Factor]` | 波动性相关 |
| `[技术因子]` / `[Technical Factor]` | 技术分析指标 |
| `[机器学习因子]` / `[ML-based Factor]` | 需要 ML 方法计算 |
| `[高频因子]` / `[HF Factor]` | 来自高频数据（需标注 not_viable） |
| `[基本面因子]` / `[Fundamental Factor]` | 来自财务数据（需标注 not_viable） |

---

## 完整提取示例

### 输入：论文描述

> "我们构建了一个 5 日价量动量因子（VMM_5），计算方法为过去 5 个交易日的成交量加权收益率之和。同时定义了 20 日波动率因子（VOL_20），采用对数收益率的 20 日滚动标准差。"

### 输出：标准化 Specification

```json
{
    "VMM_5": {
        "description": "[量价因子] 5日成交量加权动量，衡量近5日买入/卖出压力方向",
        "formulation": "VMM\\_5 = \\sum_{i=1}^{5} \\frac{Volume_{t-i}}{\\sum_{j=1}^{5} Volume_{t-j}} \\times R_{t-i}",
        "variables": {
            "Volume_{t-i}": "第 t-i 日成交量",
            "R_{t-i}": "第 t-i 日收益率 = Close_{t-i} / Close_{t-i-1} - 1"
        }
    },
    "VOL_20": {
        "description": "[波动率因子] 20日对数收益率滚动标准差，衡量近期波动水平",
        "formulation": "VOL\\_20 = \\text{std}(\\ln(Close_{t-i} / Close_{t-i-1}), i=1..20)",
        "variables": {
            "Close_{t-i}": "第 t-i 日收盘价",
            "\\text{std}()": "滚动标准差，window=20, min_periods=15"
        }
    }
}
```

---

## 数据可用性约束

从论文提取因子时，必须将论文中的数据描述**映射**到实际可用的 `daily_pv.h5` 字段：

### 可用字段（6 个）

| 字段 | 含义 | 对应论文中的常见表述 |
|------|------|-------------------|
| `$close` | 收盘价 | close, 收盘价, closing price |
| `$open` | 开盘价 | open, 开盘价, opening price |
| `$high` | 最高价 | high, 最高价, highest price |
| `$low` | 最低价 | low, 最低价, lowest price |
| `$volume` | 成交量 | volume, 成交量, 成交额, turnover（近似） |
| `$factor` | 复权因子 | adjustment factor, 复权因子 |

### 派生字段（可计算）

| 字段 | 计算方式 |
|------|---------|
| 收益率 (Return) | `close.pct_change(1)` |
| 对数收益率 (Log Return) | `np.log(close / close.shift(1))` |
| 振幅 (Amplitude) | `(high - low) / close` |
| VWAP (近似) | `(open + close + high + low) / 4` |
| 复权收盘价 | `close * factor` |

### 不可用数据（因子标记 not_viable）

| 数据类型 | 论文常见表述 | 替代方案 |
|---------|------------|---------|
| 分钟级数据 | 分钟K线、tick数据、日内 | ❌ 无替代 → not_viable |
| 财务报表 | ROE、净利润、EPS、PE | ❌ 无替代 → not_viable |
| 一致预期 | 分析师预期、盈利预测 | ❌ 无替代 → not_viable |
| 另类数据 | 新闻情感、社交媒体 | ❌ 无替代 → not_viable |
| 指数成分 | 成分股权重、行业分类 | ❌ 无替代 → not_viable |

---

## 因子筛选规则

### 自动排除

从论文中提取后，以下因子**自动排除**（标记为 `not_viable`）：
1. 依赖不可用数据的因子
2. 非日频因子（月频、季频）且无法日频化
3. 非个股维度因子（行业因子、宏观因子）
4. 纯主观判断因子（需人工标注）

### 难度评估

| 难度 | 标准 | 示例 |
|------|------|------|
| 🟢 低 | 单字段+简单运算（pct_change, rolling mean/std） | 5日收益率、20日波动率 |
| 🟡 中 | 多字段交叉或非线性变换（rank, zscore, 条件筛选） | 量价背离、条件动量 |
| 🔴 高 | ML方法、复杂递推、多步骤组合 | 隐马尔可夫、信号分解 |

---

## 因子假设生成

提取完因子 Specification 后，Agent 必须为衔接 `fin-factor` 生成一份假设文本：

```json
{
    "hypothesis": "基于论文《XX》的核心发现，XX类因子（如 factor_a, factor_b）预期能捕捉XX效应，在CSI300上产生正向IC。",
    "reason": "论文回测显示该因子在XX样本上IC=XX，ICIR=XX。本轮提取了N个因子进行验证。",
    "source": "论文标题/研报标题",
    "extracted_factors": ["factor_a", "factor_b", "factor_c"]
}
```

---

## 与 fin-factor Specification 格式对照

| 字段 | fin-paper-reader 输出 | fin-factor Step 1.5 需要 | 兼容？ |
|------|---------------------|-------------------------|--------|
| factor_name | ✅ 英文下划线 | ✅ 英文下划线 | ✅ |
| description | ✅ [类型] + 描述 | ✅ [类型] + 描述 | ✅ |
| formulation | ✅ LaTeX | ✅ LaTeX | ✅ |
| variables | ✅ 变量说明 | ✅ 变量说明 | ✅ |
| 输入约束 | ✅ 标注数据字段 | ✅ 需要知道输入 | ✅ |
| 输出约束 | — (不生成代码) | ✅ float64 MultiIndex | N/A |

> **结论**：`fin-paper-reader` 的输出可以**无缝**作为 `fin-factor` Step 1.5 的输入。
