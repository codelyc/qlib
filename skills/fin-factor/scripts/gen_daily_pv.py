#!/usr/bin/env python3
"""
生成因子计算所需的 daily_pv.h5 数据文件。
借鉴: rdagent/scenarios/qlib/experiment/factor_data_template/generate.py

在 Docker 容器中运行:
  docker run --rm \
    -v "$EXP_ROOT":/workspace/qlib_workspace/ \
    -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
    --shm-size=16g \
    local_qlib:latest \
    bash -c "cd /workspace/qlib_workspace && python gen_daily_pv.py"

产出:
  - daily_pv.h5       全量数据 (~1-2GB, 2008年至今, 全部CSI300成分股)
  - daily_pv_debug.h5  调试数据 (~30MB, 2年×100只股票，用于快速验证因子代码)
"""
import sys
import qlib

qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")
from qlib.data import D

# ── 1. 全量数据 ──────────────────────────────────────────────
print("正在生成全量数据 daily_pv.h5 ...")
instruments = D.instruments()
fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
data_all = (
    D.features(instruments, fields, freq="day")
    .swaplevel()
    .sort_index()
    .loc["2008-12-29":]
    .sort_index()
)
data_all.to_hdf("daily_pv.h5", key="data")
print(f"✅ daily_pv.h5 — shape={data_all.shape}")
print(f"   时间: {data_all.index.get_level_values('datetime').min()} ~ "
      f"{data_all.index.get_level_values('datetime').max()}")
print(f"   股票: {data_all.index.get_level_values('instrument').nunique()}")

# ── 2. 调试数据 (100只股票 × 2年) ────────────────────────────
print("\n正在生成调试数据 daily_pv_debug.h5 ...")
data_debug = (
    D.features(instruments, fields, start_time="2018-01-01", end_time="2019-12-31", freq="day")
    .swaplevel()
    .sort_index()
)
# 只保留前100只股票
top100 = data_debug.index.get_level_values("instrument").unique()[:100]
data_debug = data_debug.swaplevel().loc[top100].swaplevel().sort_index()
data_debug.to_hdf("daily_pv_debug.h5", key="data")
print(f"✅ daily_pv_debug.h5 — shape={data_debug.shape}")
print(f"   时间: {data_debug.index.get_level_values('datetime').min()} ~ "
      f"{data_debug.index.get_level_values('datetime').max()}")
print(f"   股票: {data_debug.index.get_level_values('instrument').nunique()}")

# ── 3. 写入数据结束日期 ──────────────────────────────────────
# 取全量数据的最后一个交易日，再往前退1天（避免 Qlib 回测边界越界 IndexError）
all_dates = sorted(data_all.index.get_level_values('datetime').unique())
# 倒数第2个交易日作为安全的 end_time
safe_end_date = all_dates[-2].strftime("%Y-%m-%d")
with open("data_end_date.txt", "w") as f:
    f.write(safe_end_date)
print(f"\n✅ data_end_date.txt — 安全结束日期: {safe_end_date}")
print(f"   (数据实际最后日期: {all_dates[-1].strftime('%Y-%m-%d')}，退1个交易日避免边界越界)")

print("\n🎉 数据生成完成")
