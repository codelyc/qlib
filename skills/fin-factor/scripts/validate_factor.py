#!/usr/bin/env python3
"""
因子代码快速验证脚本 — 用 debug 数据 (<30秒) 验证 factor.py 是否正确。
借鉴: rdagent/components/coder/factor_coder/evaluators.py

用法 (在本地 Python 或 Docker 中运行):
  python validate_factor.py <factor_dir>

验证项:
  1. factor.py 能否执行成功
  2. result.h5 是否生成
  3. 输出是否为 DataFrame + MultiIndex(datetime, instrument)
  4. 数据类型是否为 float64
  5. 是否有足够的非空值
  6. 时间粒度是否为日级（拒绝分钟级）

退出码: 0=通过, 1=失败
"""
import subprocess
import sys
import os
from pathlib import Path

import pandas as pd


def validate(factor_dir: str) -> bool:
    factor_dir = Path(factor_dir).resolve()
    factor_py = factor_dir / "factor.py"
    result_h5 = factor_dir / "result.h5"
    debug_data = factor_dir / "daily_pv.h5"

    errors = []

    # ── 检查文件存在 ────────────────────────────────────────
    if not factor_py.exists():
        print(f"❌ 找不到 {factor_py}")
        return False

    if not debug_data.exists():
        print(f"❌ 找不到 {debug_data}（需要先链接 daily_pv_debug.h5）")
        return False

    # ── 1. 执行 factor.py ───────────────────────────────────
    print(f"🔄 执行 {factor_py.name} ...")
    if result_h5.exists():
        result_h5.unlink()

    try:
        output = subprocess.check_output(
            [sys.executable, str(factor_py)],
            cwd=str(factor_dir),
            stderr=subprocess.STDOUT,
            timeout=120,  # debug 数据 2 分钟应该够了
        )
        print(f"   执行输出 (末尾):\n   " + output.decode()[-500:].replace("\n", "\n   "))
    except subprocess.CalledProcessError as e:
        error_msg = e.output.decode()[-1000:]
        print(f"❌ factor.py 执行失败:\n{error_msg}")
        return False
    except subprocess.TimeoutExpired:
        print(f"❌ factor.py 执行超时 (>120秒)")
        return False

    # ── 2. 检查 result.h5 是否生成 ──────────────────────────
    if not result_h5.exists():
        print(f"❌ result.h5 未生成")
        return False

    file_size = result_h5.stat().st_size
    if file_size == 0:
        print(f"❌ result.h5 文件为空")
        return False
    print(f"   result.h5 大小: {file_size / 1024:.1f} KB")

    # ── 3. 读取并验证格式 ───────────────────────────────────
    try:
        df = pd.read_hdf(result_h5, key="data")
    except Exception as e:
        print(f"❌ 无法读取 result.h5: {e}")
        return False

    # 检查是否为 DataFrame
    if not isinstance(df, pd.DataFrame):
        errors.append(f"输出不是 DataFrame，而是 {type(df)}")

    # 检查 MultiIndex
    if not isinstance(df.index, pd.MultiIndex):
        errors.append(f"index 不是 MultiIndex，而是 {type(df.index)}")
    else:
        idx_names = list(df.index.names)
        if "datetime" not in idx_names:
            errors.append(f"index 中缺少 'datetime'，当前 names={idx_names}")
        if "instrument" not in idx_names:
            errors.append(f"index 中缺少 'instrument'，当前 names={idx_names}")

    # 检查列数
    if len(df.columns) == 0:
        errors.append("DataFrame 没有列")
    elif len(df.columns) > 1:
        print(f"   ⚠️ 有 {len(df.columns)} 列，通常应只有 1 列因子值")

    # 检查数据类型
    for col in df.columns:
        if df[col].dtype != "float64":
            errors.append(f"列 '{col}' 类型是 {df[col].dtype}，应为 float64")

    # 检查非空值
    total = len(df)
    non_null = df.iloc[:, 0].notna().sum() if len(df.columns) > 0 else 0
    null_ratio = 1 - (non_null / total) if total > 0 else 1
    if null_ratio > 0.95:
        errors.append(f"NaN 比例过高: {null_ratio:.1%} (>95%)")
    print(f"   行数: {total}, 非空: {non_null}, NaN比例: {null_ratio:.1%}")

    # ── 4. 检查时间粒度（拒绝分钟级）──────────────────────
    if "datetime" in (df.index.names or []):
        dt_level = df.index.get_level_values("datetime")
        time_diffs = pd.Series(dt_level).diff().dropna().unique()
        if pd.Timedelta(minutes=1) in time_diffs:
            errors.append("检测到分钟级数据，因子应为日级")

    # ── 汇总 ────────────────────────────────────────────────
    if errors:
        print(f"\n❌ 验证失败 ({len(errors)} 个问题):")
        for i, err in enumerate(errors, 1):
            print(f"   {i}. {err}")
        return False
    else:
        print(f"\n✅ 验证通过!")
        print(f"   因子: {list(df.columns)}")
        print(f"   形状: {df.shape}")
        if isinstance(df.index, pd.MultiIndex) and "datetime" in df.index.names:
            print(f"   时间: {dt_level.min()} ~ {dt_level.max()}")
            print(f"   股票: {df.index.get_level_values('instrument').nunique()}")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python validate_factor.py <factor_dir>")
        sys.exit(1)
    ok = validate(sys.argv[1])
    sys.exit(0 if ok else 1)
