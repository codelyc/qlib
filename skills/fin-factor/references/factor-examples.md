# 因子代码示例库

以下是 8 个经过验证的因子实现模式，覆盖动量、量价、波动率、技术指标等常见类型。新因子代码应参考这些范例。

每个示例都遵循 [数据处理注释规范](./rd-agent-specs.md)，在每步数据转换处标注数据结构。

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
    # 1. 读取数据 — MultiIndex(instrument, datetime), 列: $open, $close, $high, $low, $volume, $factor
    df = pd.read_hdf("daily_pv.h5", key="data")
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument
    #    close shape: (n_days, n_stocks), volume shape: (n_days, n_stocks)
    df = df.sort_index(level=['instrument', 'datetime'])
    close = df['$close'].unstack(level='instrument').sort_index()
    volume = df['$volume'].unstack(level='instrument').sort_index()
    
    # 3. 计算因子 — shape 均为 (n_days, n_stocks)
    delta_close = close.diff(1)                          # 日涨跌额，首行 NaN
    sign_delta = np.sign(delta_close)                    # 涨跌方向 +1/-1/0
    signed_volume = sign_delta * volume                  # 带方向的成交量
    numerator = signed_volume.rolling(window=5, min_periods=5).sum()
    denominator = volume.rolling(window=5, min_periods=5).sum()
    vol_ratio5d = numerator / (denominator + 1e-8)       # epsilon 防除零
    
    # 4. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = vol_ratio5d.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vol_ratio5d')
    result = result.astype('float64')
    result.to_hdf("result.h5", key="data")
    
    # 5. 诊断输出
    print(f"shape: {result.shape}")
    print(f"non-null: {result['vol_ratio5d'].notna().sum()}")
    print(result.head(10))

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
    # 1. 读取数据 — MultiIndex(instrument, datetime), 列: $open, $close, ...
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()
    
    # 3. 计算因子 — shape: (n_days, n_stocks)，前 60 行为 NaN（回看期不足）
    #    注意：shift(60) 回看 60 天历史，正数 = 回看，无未来泄露
    mom60d = close / (close.shift(60) + 1e-8) - 1
    
    # 4. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    #    ⚠️ 不用 dropna()，保留 NaN 由 Qlib 处理，避免破坏索引完整性
    result = mom60d.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='mom60d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    # 5. 诊断输出
    print(f"shape: {result.shape}")
    print(f"non-null: {result['mom60d'].notna().sum()}")
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
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()
    
    # 3. 日收益率 — shape: (n_days, n_stocks)，首行 NaN
    daily_ret = close.pct_change(1)
    
    # 4. 20日滚动偏度 — shape: (n_days, n_stocks)，前 min_periods-1 行 NaN
    vol_skew = daily_ret.rolling(window=20, min_periods=15).skew()
    
    # 5. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = vol_skew.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vol_skew20d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['vol_skew20d'].notna().sum()}")
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
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()
    volume = df['$volume'].unstack(level='instrument').sort_index()
    
    # 3. 20日滚动相关性 — shape: (n_days, n_stocks)
    vp_corr = close.rolling(window=20, min_periods=15).corr(volume)
    
    # 4. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = vp_corr.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vp_divergence')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['vp_divergence'].notna().sum()}")
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
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    high = df['$high'].unstack(level='instrument').sort_index()
    low = df['$low'].unstack(level='instrument').sort_index()
    open_price = df['$open'].unstack(level='instrument').sort_index()
    
    # 3. 日内振幅比 — shape: (n_days, n_stocks)，epsilon 防除零
    daily_range = (high - low) / (open_price + 1e-8)
    
    # 4. 10日滚动均值 — shape: (n_days, n_stocks)
    avg_range = daily_range.rolling(window=10, min_periods=8).mean()
    
    # 5. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = avg_range.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='intraday_range')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['intraday_range'].notna().sum()}")
    print(result.head(10))

if __name__ == '__main__':
    calculate_intraday_range()
```

---

## 示例 6：RSI 相对强弱因子 (rsi14d)

**类型**：技术指标因子  
**思路**：14日 RSI 衡量价格上涨动力占比，超买/超卖信号

```python
import pandas as pd
import numpy as np

def calculate_rsi14d():
    """
    [技术指标因子] 14日相对强弱指数
    公式: RSI = 100 - 100 / (1 + RS)
           RS = EMA(gain, 14) / EMA(loss, 14)
    """
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()
    
    # 3. 日涨跌额 — shape: (n_days, n_stocks)，首行 NaN
    delta = close.diff(1)
    
    # 4. 分离涨跌 — shape 不变: (n_days, n_stocks)
    gain = delta.clip(lower=0)    # 上涨部分，下跌日为 0
    loss = (-delta).clip(lower=0) # 下跌部分（取正值），上涨日为 0
    
    # 5. 14日指数移动平均 — shape: (n_days, n_stocks)
    avg_gain = gain.ewm(span=14, min_periods=10).mean()
    avg_loss = loss.ewm(span=14, min_periods=10).mean()
    
    # 6. 计算 RSI — epsilon 防除零
    rs = avg_gain / (avg_loss + 1e-8)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    
    # 7. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = rsi.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='rsi14d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['rsi14d'].notna().sum()}")
    print(result.head(10))

if __name__ == '__main__':
    calculate_rsi14d()
```

---

## 示例 7：VWAP 偏离因子 (vwap_bias5d)

**类型**：量价关系因子  
**思路**：收盘价相对 VWAP（成交量加权平均价）的偏离度，衡量当前价格是否高于近期"公允价"

```python
import pandas as pd
import numpy as np

def calculate_vwap_bias5d():
    """
    [量价因子] 5日VWAP偏离度
    公式: VWAP_Bias = (Close - VWAP_5) / VWAP_5
           VWAP_5 = sum(Close_i * Volume_i, i=1..5) / sum(Volume_i, i=1..5)
    """
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    close = df['$close'].unstack(level='instrument').sort_index()
    volume = df['$volume'].unstack(level='instrument').sort_index()
    
    # 3. 计算成交额 — shape: (n_days, n_stocks)
    turnover = close * volume
    
    # 4. 5日滚动 VWAP — shape: (n_days, n_stocks)
    sum_turnover = turnover.rolling(window=5, min_periods=5).sum()
    sum_volume = volume.rolling(window=5, min_periods=5).sum()
    vwap5 = sum_turnover / (sum_volume + 1e-8)  # epsilon 防除零
    
    # 5. 偏离度 — shape: (n_days, n_stocks)
    vwap_bias = (close - vwap5) / (vwap5 + 1e-8)
    
    # 6. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = vwap_bias.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='vwap_bias5d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['vwap_bias5d'].notna().sum()}")
    print(result.head(10))

if __name__ == '__main__':
    calculate_vwap_bias5d()
```

---

## 示例 8：异常换手率因子 (turnover_anomaly20d)

**类型**：流动性因子  
**思路**：当日换手率相对 20 日均值的偏离程度，异常放量/缩量可能预示变盘

```python
import pandas as pd
import numpy as np

def calculate_turnover_anomaly20d():
    """
    [流动性因子] 20日换手率异常度
    公式: Turnover_Anomaly = (Volume_t - Mean(Volume, 20)) / Std(Volume, 20)
    即 Z-Score 标准化，衡量当日成交量的异常程度
    """
    # 1. 读取数据 — MultiIndex(instrument, datetime)
    df = pd.read_hdf('daily_pv.h5', key='data')
    
    # 2. 透视为宽表 — 行: datetime, 列: instrument, shape: (n_days, n_stocks)
    volume = df['$volume'].unstack(level='instrument').sort_index()
    
    # 3. 20日滚动均值和标准差 — shape: (n_days, n_stocks)
    vol_mean = volume.rolling(window=20, min_periods=15).mean()
    vol_std = volume.rolling(window=20, min_periods=15).std()
    
    # 4. Z-Score — epsilon 防除零
    turnover_anomaly = (volume - vol_mean) / (vol_std + 1e-8)
    
    # 5. 清除无穷大值
    turnover_anomaly = turnover_anomaly.replace([np.inf, -np.inf], np.nan)
    
    # 6. 转回长表 — MultiIndex(datetime, instrument), 单列 float64
    result = turnover_anomaly.stack()
    result.index.names = ['datetime', 'instrument']
    result = result.to_frame(name='turnover_anomaly20d')
    result = result.astype('float64')
    result.to_hdf('result.h5', key='data')
    
    print(f"shape: {result.shape}")
    print(f"non-null: {result['turnover_anomaly20d'].notna().sum()}")
    print(result.head(10))

if __name__ == '__main__':
    calculate_turnover_anomaly20d()
```

---

## 代码编写常见错误

| 错误 | 原因 | 修复方法 |
|------|------|---------|
| `KeyError: 'datetime'` | index 名称不对 | 确认 `result.index.names = ['datetime', 'instrument']` |
| `result.h5 为空` | dropna 后无数据 | **禁止**对结果 dropna，保留 NaN 由 Qlib 处理 |
| `数据格式不匹配` | 没有 unstack/stack | 确保最终格式是 MultiIndex(datetime, instrument) |
| `时间泄露` | 用了未来数据（如 shift(-N)） | 所有 shift 必须是正数（回看历史） |
| `NaN 太多` | rolling window 太大 | 减小 window 或降低 min_periods |
| `除零产生 inf` | 分母为 0 | 分母加 `+ 1e-8` |
| `NaN 比例 > 80%` | 逻辑错误或 window 过大 | 检查 min_periods、数据范围、计算逻辑 |
