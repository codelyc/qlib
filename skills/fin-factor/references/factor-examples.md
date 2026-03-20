# 因子代码示例库

以下是经过验证的因子实现模式，新因子代码应参考这些范例。

---

## 示例 1：成交量比率因子 (vol_ratio5d)

**类型**：量价关系因子  
**思路**：衡量近 5 日上涨日成交量 vs 下跌日成交量的比值，反映资金方向

```python
import pandas as pd
import numpy as np

def calculate_vol_ratio5d():
    """
    [量价因子] 5日成交量方向比率
    公式: Vol_Ratio = sum(sign(ΔClose_i) * Volume_i, i=1..5) / sum(Volume_i, i=1..5)
    """
    # 1. 读取数据
    df = pd.read_hdf("daily_pv.h5", key="data")
    # df: MultiIndex(instrument, datetime), 列: $open, $close, $high, $low, $volume
    
    # 2. 透视为宽表
    df = df.sort_index(level=['instrument', 'datetime'])
    close = df['$close'].unstack(level='instrument')  # shape: (n_days, n_stocks)
    volume = df['$volume'].unstack(level='instrument')
    close = close.sort_index()
    volume = volume.sort_index()
    
    # 3. 计算因子
    delta_close = close.diff(1)
    sign_delta = np.sign(delta_close)
    signed_volume = sign_delta * volume
    numerator = signed_volume.rolling(window=5, min_periods=5).sum()
    denominator = volume.rolling(window=5, min_periods=5).sum()
    vol_ratio5d = numerator / denominator
    
    # 4. 转回长表并保存
    result = vol_ratio5d.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vol_ratio5d')
    result = result.astype('float64')
    result.to_hdf("result.h5", key="data")
    
    print(result.info())
    print(result.head(10))
    print(f"Non-null count: {result['vol_ratio5d'].notna().sum()}")

if __name__ == "__main__":
    calculate_vol_ratio5d()
```

---

## 示例 2：60日动量因子 (mom60d)

**类型**：动量因子  
**思路**：过去 60 天收益率，捕捉中期趋势

```python
import pandas as pd
import numpy as np

def calculate_mom60d():
    """
    [动量因子] 60日价格动量
    公式: Mom_60 = Close_t / Close_{t-60} - 1
    """
    df = pd.read_hdf('daily_pv.h5', key='data')
    close = df['$close'].unstack(level='instrument')
    
    mom60d = close / close.shift(60) - 1
    
    result = mom60d.stack()
    result.name = 'mom60d'
    result = result.to_frame()
    result.index.names = ['datetime', 'instrument']
    result = result.dropna()
    result.to_hdf('result.h5', key='data')
    
    print(result.info())
    print(result.head(10))

if __name__ == '__main__':
    calculate_mom60d()
```

---

## 示例 3：波动率偏度因子 (vol_skew20d)

**类型**：波动率因子  
**思路**：衡量收益率分布的不对称性

```python
import pandas as pd
import numpy as np

def calculate_vol_skew20d():
    """
    [波动率因子] 20日收益率偏度
    公式: Skew_20 = E[(r - μ)³] / σ³, r = daily_return over 20 days
    """
    df = pd.read_hdf('daily_pv.h5', key='data')
    close = df['$close'].unstack(level='instrument')
    close = close.sort_index()
    
    # 日收益率
    daily_ret = close.pct_change(1)
    
    # 20日滚动偏度
    vol_skew = daily_ret.rolling(window=20, min_periods=15).skew()
    
    result = vol_skew.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vol_skew20d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(result.info())
    print(result.head(10))

if __name__ == '__main__':
    calculate_vol_skew20d()
```

---

## 示例 4：量价背离因子 (vp_divergence)

**类型**：量价关系因子  
**思路**：价格上涨但成交量萎缩（看跌信号），或价格下跌但成交量放大（看跌信号）

```python
import pandas as pd
import numpy as np

def calculate_vp_divergence():
    """
    [量价因子] 20日量价背离度
    公式: VP_Div = Corr(Close_rank_20, Volume_rank_20)
    负值表示量价背离
    """
    df = pd.read_hdf('daily_pv.h5', key='data')
    close = df['$close'].unstack(level='instrument')
    volume = df['$volume'].unstack(level='instrument')
    close = close.sort_index()
    volume = volume.sort_index()
    
    # 20日滚动相关性
    vp_corr = close.rolling(window=20, min_periods=15).corr(volume)
    
    result = vp_corr.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vp_divergence')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(result.info())
    print(result.head(10))

if __name__ == '__main__':
    calculate_vp_divergence()
```

---

## 示例 5：日内振幅因子 (intraday_range)

**类型**：波动率因子  
**思路**：日内最高价与最低价之差，反映日内波动

```python
import pandas as pd
import numpy as np

def calculate_intraday_range():
    """
    [波动率因子] 10日平均日内振幅
    公式: Range_10 = Mean((High - Low) / Open, 10)
    """
    df = pd.read_hdf('daily_pv.h5', key='data')
    high = df['$high'].unstack(level='instrument')
    low = df['$low'].unstack(level='instrument')
    open_price = df['$open'].unstack(level='instrument')
    
    high = high.sort_index()
    low = low.sort_index()
    open_price = open_price.sort_index()
    
    daily_range = (high - low) / open_price
    avg_range = daily_range.rolling(window=10, min_periods=8).mean()
    
    result = avg_range.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='intraday_range')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(result.info())
    print(result.head(10))

if __name__ == '__main__':
    calculate_intraday_range()
```

---

## 代码编写常见错误

| 错误 | 原因 | 修复方法 |
|------|------|---------|
| `KeyError: 'datetime'` | index 名称不对 | 确认 `result.index.names = ['datetime', 'instrument']` |
| `result.h5 为空` | dropna 后无数据 | 检查 rolling 的 min_periods 是否太大 |
| `数据格式不匹配` | 没有 unstack/stack | 确保最终格式是 MultiIndex(datetime, instrument) |
| `时间泄露` | 用了未来数据（如 shift(-N)） | 所有 shift 必须是正数（回看历史） |
| `NaN 太多` | rolling window 太大 | 减小 window 或降低 min_periods |
