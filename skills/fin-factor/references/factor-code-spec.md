# 因子代码规范

## 模板

每个因子一个独立文件 `$ROUND_DIR/{因子名}/factor.py`。

**代码中每一步数据转换都必须附带注释，明确说明当前数据结构**（索引类型、列名、形状），详见 [rd-agent-specs.md](./rd-agent-specs.md) 中的 `数据处理注释规范`。

```python
import pandas as pd
import numpy as np

def calculate_factor_name():
    """
    [因子类型] 因子描述
    公式: ...
    """
    # 1. 读取数据 — MultiIndex(instrument, datetime), 列: $open, $close, $high, $low, $volume, $factor
    df = pd.read_hdf("daily_pv.h5", key="data")

    # 2. 透视为宽表 — 行: datetime, 列: instrument（每列一只股票的收盘价）
    #    shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()

    # 3. 计算因子值 — shape 不变: (n_days, n_stocks)
    factor_values = ...  # 你的计算逻辑

    # 4. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    #    注意：stack 后索引顺序自动变为 (datetime, instrument)
    result = factor_values.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='factor_name')
    result = result.astype('float64')

    # 5. 保存
    result.to_hdf("result.h5", key="data")

    # 6. 诊断输出
    print(f"shape: {result.shape}")
    print(f"non-null: {result.iloc[:, 0].notna().sum()}")
    print(result.head(10))

if __name__ == "__main__":
    calculate_factor_name()
```

## 强制要求

- 数据源：`daily_pv.h5`（从工作空间自动链接）
- 输出：`result.h5`，key="data"，MultiIndex(datetime, instrument)，单列 float64
- **禁止** try-except — 让错误暴露
- **禁止**使用未来数据（时间泄露）
- 所有 shift 必须为正数（回看历史）
- **禁止**对结果使用 `dropna()` — 会破坏 MultiIndex 完整性，导致空表（用 NaN 保留即可，Qlib 会处理）

## 鲁棒性写法（必须遵守）

### 除零保护（epsilon）

涉及除法时，**必须**在分母加 epsilon 防止除零：

```python
# ❌ 错误：分母可能为 0
ratio = numerator / denominator

# ✅ 正确：加 epsilon 保护
ratio = numerator / (denominator + 1e-8)

# ✅ 也可用 np.where 处理
ratio = np.where(np.abs(denominator) < 1e-8, 0.0, numerator / denominator)
```

### 无穷大清洗

计算完成后，清除可能产生的无穷大值：

```python
factor_values = factor_values.replace([np.inf, -np.inf], np.nan)
```

### rolling 的 min_periods

始终设置 `min_periods`，避免窗口不足时产生不可靠结果：

```python
# ❌ 错误：默认 min_periods=window，前 window-1 行全为 NaN
result = series.rolling(window=20).mean()

# ✅ 正确：设置合理的 min_periods（通常为 window 的 60%-80%）
result = series.rolling(window=20, min_periods=15).mean()
```

## Qlib 可用数据字段

| 字段 | 含义 | daily_pv.h5 列名 |
|------|------|-----------------|
| 开盘价 | Open | `$open` |
| 收盘价 | Close | `$close` |
| 最高价 | High | `$high` |
| 最低价 | Low | `$low` |
| 成交量 | Volume | `$volume` |
| 复权因子 | Adj Factor | `$factor` |

数据 index 格式：MultiIndex(instrument, datetime)。

## 常见错误

| 错误 | 原因 | 修复 |
|------|------|------|
| `KeyError: 'datetime'` | index 名称不对 | `result.index.names = ['datetime', 'instrument']` |
| result.h5 为空 | dropna 后无数据 | **禁止**对结果 dropna，保留 NaN 即可 |
| 时间泄露 | 用了 shift(-N) | 所有 shift 必须为正数 |
| NaN 太多 | rolling window 太大 | 减小 window 或降低 min_periods |
| 除零产生 inf | 分母为 0 | 分母加 `+ 1e-8` |
| NaN 比例 > 80% | 逻辑错误或 window 过大 | 检查 min_periods、数据范围、计算逻辑 |

> 📖 更多完整示例见 [factor-examples.md](./factor-examples.md)（8 个经过验证的因子实现）
