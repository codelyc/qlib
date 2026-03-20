#!/usr/bin/env python3
"""
因子合并脚本 — 将多个因子的 result.h5 合并为 combined_factors_df.parquet。
借鉴: rdagent/scenarios/qlib/developer/factor_runner.py (deduplicate + merge + MultiIndex columns)

用法:
  python merge_factors.py <round_dir> [--sota-file <path>]

功能:
  1. 扫描 round_dir 下所有子目录的 result.h5
  2. 验证每个因子的输出格式 (MultiIndex, 日级数据)
  3. 与 SOTA 因子去重 (IC 相关性 > 0.99 则剔除)
  4. 合并后添加 MultiIndex columns: ("feature", factor_name) — Qlib StaticDataLoader 格式
  5. 保存为 combined_factors_df.parquet
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def load_and_validate_factor(result_h5: Path) -> Optional[pd.DataFrame]:
    """加载单个因子并验证格式"""
    try:
        df = pd.read_hdf(result_h5, key="data")
    except Exception as e:
        print(f"  ❌ 读取失败 {result_h5}: {e}")
        return None

    if not isinstance(df, pd.DataFrame):
        print(f"  ❌ 不是 DataFrame: {result_h5}")
        return None

    if not isinstance(df.index, pd.MultiIndex) or "datetime" not in df.index.names:
        print(f"  ❌ 缺少 MultiIndex(datetime, instrument): {result_h5}")
        return None

    # 拒绝分钟级数据
    dt_vals = df.index.get_level_values("datetime")
    time_diffs = pd.Series(dt_vals).diff().dropna().unique()
    if pd.Timedelta(minutes=1) in time_diffs:
        print(f"  ❌ 检测到分钟级数据，已跳过: {result_h5}")
        return None

    return df.astype("float64")


def deduplicate_factors(
    sota_df: pd.DataFrame, new_df: pd.DataFrame, threshold: float = 0.99
) -> pd.DataFrame:
    """
    去重：移除与 SOTA 因子高度相关 (IC > threshold) 的新因子。
    借鉴: QlibFactorRunner.deduplicate_new_factors()
    """
    if sota_df.empty or new_df.empty:
        return new_df

    keep_cols = []
    for new_col in new_df.columns:
        max_ic = 0.0
        max_sota_col = ""
        for sota_col in sota_df.columns:
            # 按日期分组计算相关性，取均值 — 比全局 corr 更精确
            try:
                merged = pd.concat([sota_df[[sota_col]], new_df[[new_col]]], axis=1).dropna()
                if len(merged) < 100:
                    continue
                if "datetime" in merged.index.names:
                    ic = (
                        merged.groupby("datetime")
                        .apply(lambda g: g.iloc[:, 0].corr(g.iloc[:, 1]))
                        .mean()
                    )
                else:
                    ic = merged.iloc[:, 0].corr(merged.iloc[:, 1])
                if abs(ic) > max_ic:
                    max_ic = abs(ic)
                    max_sota_col = sota_col
            except Exception:
                continue

        if max_ic >= threshold:
            print(f"  ⚠️ 去重: {new_col} 与 SOTA 因子 {max_sota_col} 高度相关 (IC={max_ic:.4f})")
        else:
            keep_cols.append(new_col)

    if not keep_cols:
        print("  ⚠️ 所有新因子都与 SOTA 重复！")
        return pd.DataFrame()

    return new_df[keep_cols]


def merge_factors(round_dir: str, sota_file: Optional[str] = None) -> Optional[pd.DataFrame]:
    """合并本轮所有因子 + SOTA 因子"""
    round_path = Path(round_dir).resolve()
    new_factors = []
    factor_names = []

    print(f"📁 扫描目录: {round_path}")

    # 遍历子目录找 result.h5
    for sub_dir in sorted(round_path.iterdir()):
        if not sub_dir.is_dir():
            continue
        result_file = sub_dir / "result.h5"
        if not result_file.exists():
            continue

        print(f"\n  加载因子: {sub_dir.name}")
        df = load_and_validate_factor(result_file)
        if df is not None:
            print(f"  ✅ shape={df.shape}, cols={list(df.columns)}")
            new_factors.append(df)
            factor_names.append(sub_dir.name)
        else:
            print(f"  ⏭️  跳过 {sub_dir.name}")

    if not new_factors:
        print("\n❌ 没有找到有效的因子文件")
        return None

    # 合并新因子
    new_combined = pd.concat(new_factors, axis=1)
    # 去重列名 (保留最后一个)
    new_combined = new_combined.loc[:, ~new_combined.columns.duplicated(keep="last")]
    print(f"\n新因子合并: {new_combined.shape} ({list(new_combined.columns)})")

    # 加载 SOTA 因子并去重
    sota_df = pd.DataFrame()
    if sota_file and Path(sota_file).exists():
        try:
            sota_df = pd.read_parquet(sota_file)
            # 如果有 MultiIndex columns，展平
            if isinstance(sota_df.columns, pd.MultiIndex):
                sota_df.columns = sota_df.columns.get_level_values(-1)
            print(f"SOTA 因子: {sota_df.shape} ({list(sota_df.columns)})")
        except Exception as e:
            print(f"⚠️ 加载 SOTA 失败: {e}")
            sota_df = pd.DataFrame()

    if not sota_df.empty:
        new_combined = deduplicate_factors(sota_df, new_combined)
        if new_combined.empty:
            print("❌ 去重后无新因子，仅使用 SOTA 因子")
            combined = sota_df
        else:
            combined = pd.concat([sota_df, new_combined], axis=1).dropna()
    else:
        combined = new_combined

    combined = combined.sort_index()
    combined = combined.loc[:, ~combined.columns.duplicated(keep="last")]

    # 转为 MultiIndex columns: ("feature", factor_name) — Qlib StaticDataLoader 格式
    new_columns = pd.MultiIndex.from_product([["feature"], combined.columns])
    combined.columns = new_columns

    # 保存
    output_path = round_path / "combined_factors_df.parquet"
    combined.to_parquet(output_path, engine="pyarrow")

    print(f"\n💾 已保存: {output_path}")
    print(f"   因子数: {len(combined.columns)}")
    print(f"   样本数: {len(combined)}")

    return combined


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="合并量化因子")
    parser.add_argument("round_dir", help="本轮工作目录")
    parser.add_argument("--sota-file", help="SOTA 因子 parquet 文件路径", default=None)
    args = parser.parse_args()

    result = merge_factors(args.round_dir, args.sota_file)
    sys.exit(0 if result is not None else 1)
