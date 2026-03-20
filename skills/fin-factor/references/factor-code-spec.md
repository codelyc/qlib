# 因子代码规范

## 模板

每个因子一个独立文件 `$ROUND_DIR/{因子名}/factor.py`：

```python
import pandas as pd
import numpy as np

def calculate_factor_name():
    """
    [因子类型] 因子描述
    公式: ...
    """
    # 1. 读取数据 — 必须从 daily_pv.h5 读取
    df = pd.read_hdf("daily_pv.h5", key="data")
    # df: MultiIndex(instrument, datetime), 列: $open, $close, $high, $low, $volume, $factor

    # 2. 透视为宽表
    close = df['$close'].unstack(level='instrument').sort_index()

    # 3. 计算因子值
    factor_values = ...  # 你的计算逻辑

    # 4. 转回长表
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
| result.h5 为空 | dropna 后无数据 | 检查 rolling 的 min_periods |
| 时间泄露 | 用了 shift(-N) | 所有 shift 必须为正数 |
| NaN 太多 | rolling window 太大 | 减小 window 或降低 min_periods |
