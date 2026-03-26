#!/usr/bin/env python3
"""
生成因子计算所需的 daily_pv.h5 数据文件。
借鉴: rdagent/scenarios/qlib/experiment/factor_data_template/generate.py

在 Docker 容器中运行:
  docker run --rm \
    -v "$EXP_ROOT":/workspace/qlib_workspace/ \
    -v "$PROJECT_ROOT/qlib/data":/qlib_data \
    --shm-size=16g \
    local_qlib:latest \
    bash -c "cd /workspace/qlib_workspace && python gen_daily_pv.py"

产出:
  - daily_pv.h5       全量数据 (~1-2GB, 2008年至今, 全部CSI300成分股)
  - daily_pv_debug.h5  调试数据 (~30MB, 2年×100只股票，用于快速验证因子代码)

参数:
  --start-date  全量数据起始日期（默认 2008-12-29）
"""
import argparse
import os
import sys
import qlib

# Docker 内默认数据路径（对应 -v $PROJECT_ROOT/qlib/data:/qlib_data），支持环境变量覆盖
provider = os.environ.get("QLIB_PROVIDER_URI", "/qlib_data")
qlib.init(provider_uri=provider)
from qlib.data import D

parser = argparse.ArgumentParser(description="生成 daily_pv.h5 数据文件")
parser.add_argument(
    "--start-date",
    default=os.environ.get("DATA_START_DATE", "2020-01-01"),
    help="全量数据起始日期 (默认读 .env 的 DATA_START_DATE，否则 2020-01-01)",
)
parser.add_argument(
    "--debug-start",
    default=os.environ.get("DEBUG_START_DATE", "2020-01-01"),
    help="debug 数据起始日期 (默认读 .env 的 DEBUG_START_DATE)",
)
parser.add_argument(
    "--debug-end",
    default=os.environ.get("DEBUG_END_DATE", "2021-12-31"),
    help="debug 数据结束日期 (默认读 .env 的 DEBUG_END_DATE)",
)
args = parser.parse_args()

# ── 1. 全量数据 ──────────────────────────────────────────────
print(f"正在生成全量数据 daily_pv.h5 (起始: {args.start_date}) ...")
# 使用 csi300 历史成分股池（比 all 更可靠，避免缺失 bin 文件导致 IndexError）
instruments = D.instruments(market="csi300")
fields = ["$open", "$close", "$high", "$low", "$volume", "$factor"]
data_all = (
    D.features(instruments, fields, start_time=args.start_date, freq="day")
    .swaplevel()
    .sort_index()
)
data_all.to_hdf("daily_pv.h5", key="data")
print(f"✅ daily_pv.h5 — shape={data_all.shape}")
print(f"   时间: {data_all.index.get_level_values('datetime').min()} ~ "
      f"{data_all.index.get_level_values('datetime').max()}")
print(f"   股票: {data_all.index.get_level_values('instrument').nunique()}")

# ── 2. 调试数据 (100只股票 × 2年) ────────────────────────────
print(f"\n正在生成调试数据 daily_pv_debug.h5 ({args.debug_start} ~ {args.debug_end}) ...")
data_debug = (
    D.features(instruments, fields, start_time=args.debug_start, end_time=args.debug_end, freq="day")
    .swaplevel()
    .sort_index()
)
if data_debug.empty:
    print(f"⚠️  debug 数据为空！请检查 DEBUG_START_DATE/DEBUG_END_DATE 是否在实际数据覆盖范围内。")
    print(f"   当前设置: {args.debug_start} ~ {args.debug_end}")
    print(f"   全量数据范围: {data_all.index.get_level_values('datetime').min().date()} ~ "
          f"{data_all.index.get_level_values('datetime').max().date()}")
# 只保留前 100 只股票
top100 = data_debug.index.get_level_values("instrument").unique()[:100]
data_debug = data_debug.swaplevel().loc[top100].swaplevel().sort_index()
data_debug.to_hdf("daily_pv_debug.h5", key="data")
print(f"✅ daily_pv_debug.h5 — shape={data_debug.shape}")
if not data_debug.empty:
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
