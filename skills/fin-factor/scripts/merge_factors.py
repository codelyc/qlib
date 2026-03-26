#!/usr/bin/env python3
"""
因子合并脚本 — 将多个因子的 result.h5 合并为 combined_factors_df.parquet。
借鉴: rdagent/scenarios/qlib/developer/factor_runner.py (deduplicate + merge + MultiIndex columns)

用法:
  # 合并所有因子（默认模式，与原有行为一致）
  python merge_factors.py <round_dir> [--sota-file <path>]

  # 单因子模式：只取指定因子，输出到因子子目录
  python merge_factors.py <round_dir> --single <factor_name> [--sota-file <path>]

功能:
  1. 扫描 round_dir 下所有子目录的 result.h5（或 --single 指定的单个因子）
  2. 验证每个因子的输出格式 (MultiIndex, 日级数据)
  3. 与 SOTA 因子去重 (IC 相关性 > 0.99 则剔除)
  4. 合并后添加 MultiIndex columns: ("feature", factor_name) — Qlib StaticDataLoader 格式
  5. 保存为 combined_factors_df.parquet 或 single_factor_df.parquet
"""
import argparse
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _read_hdf_compat(path: Path, key: str = "data") -> pd.DataFrame:
    """读取 HDF5 文件，兼容 pandas 版本差异（datetime64[ns] 索引类型问题）"""
    try:
        return pd.read_hdf(path, key=key)
    except Exception:
        # pandas 2.x 与 Docker 内 pandas 版本不一致时，
        # datetime64[ns] 索引类型可能无法识别。使用 monkey-patch 修复。
        import pandas.io.pytables as pytables
        orig_fn = pytables._unconvert_index
        def _patched(data, kind, encoding=None, errors="strict"):
            if kind == "datetime64" or (isinstance(kind, str) and kind.startswith("datetime64")):
                return pd.DatetimeIndex(data)
            return orig_fn(data, kind, encoding, errors)
        pytables._unconvert_index = _patched
        try:
            return pd.read_hdf(path, key=key)
        finally:
            pytables._unconvert_index = orig_fn


def load_and_validate_factor(result_h5: Path) -> Optional[pd.DataFrame]:
    """加载单个因子并验证格式"""
    try:
        df = _read_hdf_compat(result_h5)
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
        removed = [c for c in new_df.columns if c not in keep_cols]
        print(f"  ❌ 所有新因子都与 SOTA 高度相关，已全部去重！")
        print(f"     被去重的因子: {removed}")
        print(f"     建议: 尝试不同思路的因子（换公式/换特征/换时间窗口）")
        # 返回空 DataFrame 并标记 dedup_all=True，让调用方能感知
        result = pd.DataFrame()
        result.attrs["dedup_all"] = True
        return result

    removed = [c for c in new_df.columns if c not in keep_cols]
    if removed:
        print(f"  📋 去重日志: 保留 {keep_cols}，去除 {removed}")
    return new_df[keep_cols]


def merge_factors(
    round_dir: str,
    sota_file: Optional[str] = None,
    single_factor: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """合并本轮所有因子 + SOTA 因子。

    Args:
        round_dir: 本轮工作目录
        sota_file: SOTA 因子 parquet 文件路径
        single_factor: 若指定，只取该因子（用于单因子独立回测）
    """
    round_path = Path(round_dir).resolve()
    new_factors = []
    factor_names = []

    if single_factor:
        # ── 单因子模式 ─────────────────────────────────────────
        factor_dir = round_path / single_factor
        result_file = factor_dir / "result.h5"
        print(f"📁 单因子模式: {single_factor}")
        if not factor_dir.is_dir() or not result_file.exists():
            print(f"  ❌ 找不到 {result_file}")
            return None
        df = load_and_validate_factor(result_file)
        if df is not None:
            print(f"  ✅ shape={df.shape}, cols={list(df.columns)}")
            new_factors.append(df)
            factor_names.append(single_factor)
        else:
            print(f"  ❌ 验证失败: {single_factor}")
            return None
    else:
        # ── 全量模式（原有逻辑）──────────────────────────────
        print(f"📁 扫描目录: {round_path}")
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

    # 加载 SOTA 因子并去重（单因子模式跳过去重，直接输出单因子即可）
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

    if single_factor:
        # 单因子模式：不去重，直接使用该因子（目的是观察单因子的独立增量贡献）
        combined = new_combined
        print(f"  ℹ️ 单因子模式: 跳过 IC 去重")
    elif not sota_df.empty:
        new_combined = deduplicate_factors(sota_df, new_combined)
        if new_combined.empty:
            if new_combined.attrs.get("dedup_all"):
                # 所有新因子都被去重 → 需要换思路，退出码 2 供 Agent 判断
                err_msg = "所有新因子与 SOTA 高度相关（IC>0.99），全部被去重，需要更换因子思路"
                print(f"\n❌ {err_msg}")
                _auto_record_merge_error(str(round_path), err_msg, "dedup_all")
                sys.exit(2)
            print("⚠️ 去重后无新因子，仅使用 SOTA 因子")
            combined = sota_df
        else:
            combined = pd.concat([sota_df, new_combined], axis=1)
    else:
        combined = new_combined

    combined = combined.sort_index()
    combined = combined.loc[:, ~combined.columns.duplicated(keep="last")]

    # 转为 MultiIndex columns: ("feature", factor_name) — Qlib StaticDataLoader 格式
    new_columns = pd.MultiIndex.from_product([["feature"], combined.columns])
    combined.columns = new_columns

    # 保存 — 单因子模式输出到因子子目录，全量模式输出到 round_dir
    if single_factor:
        output_path = round_path / single_factor / "single_factor_df.parquet"
    else:
        output_path = round_path / "combined_factors_df.parquet"
    combined.to_parquet(output_path, engine="pyarrow")

    print(f"\n💾 已保存: {output_path}")
    print(f"   因子数: {len(combined.columns)}")
    print(f"   样本数: {len(combined)}")

    return combined


def _auto_record_merge_error(round_dir: str, error_msg: str, error_type: str = "merge"):
    """合并失败时自动记录到错误知识库"""
    round_path = Path(round_dir).resolve()
    exp_root = round_path.parent  # round_dir -> exp_root
    collect_py = exp_root / "collect_error.py"
    if not collect_py.exists():
        return
    import re as _re
    round_num = 0
    m = _re.search(r"round[_\-]?(\d+)", round_path.name, _re.IGNORECASE)
    if m:
        round_num = int(m.group(1))
    try:
        import subprocess
        subprocess.run(
            [
                sys.executable, str(collect_py), "record",
                "--exp-root", str(exp_root),
                "--round", str(round_num),
                "--stage", "merge",
                "--error", error_msg[:200],
                "--error-type", error_type,
            ],
            check=False, capture_output=True,
        )
    except Exception:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="合并量化因子")
    parser.add_argument("round_dir", help="本轮工作目录")
    parser.add_argument("--sota-file", help="SOTA 因子 parquet 文件路径", default=None)
    parser.add_argument(
        "--single",
        metavar="FACTOR_NAME",
        help="单因子模式：只取指定因子，输出到因子子目录的 single_factor_df.parquet",
        default=None,
    )
    args = parser.parse_args()

    result = merge_factors(args.round_dir, args.sota_file, single_factor=args.single)
    if result is None:
        _auto_record_merge_error(args.round_dir, "没有找到有效的因子文件 (result.h5)", "data_missing")
        sys.exit(1)
    sys.exit(0)
