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


def validate(factor_dir: str):
    """验证因子输出。返回 (ok: bool, errors: list)"""
    factor_dir = Path(factor_dir).resolve()
    factor_py = factor_dir / "factor.py"
    result_h5 = factor_dir / "result.h5"

    # daily_pv.h5 查找顺序：
    #   1. factor_dir/daily_pv.h5      ← SKILL.md 指导 cp 到此处
    #   2. factor_dir/daily_pv_debug.h5 ← 备选
    #   3. round_dir/daily_pv_debug.h5  ← 兼容旧流程
    #   4. round_dir/daily_pv.h5        ← 最终 fallback
    round_dir = factor_dir.parent
    debug_data = None
    for candidate in [
        factor_dir / "daily_pv.h5",
        factor_dir / "daily_pv_debug.h5",
        round_dir / "daily_pv_debug.h5",
        round_dir / "daily_pv.h5",
    ]:
        if candidate.exists():
            debug_data = candidate
            break

    errors = []

    # ── 检查文件存在 ────────────────────────
    if not factor_py.exists():
        msg = f"找不到 factor.py: {factor_py}"
        print(f"❌ {msg}")
        return False, [msg]

    if debug_data is None:
        msg = "找不到 daily_pv 数据文件（请先运行 init_workspace.sh）"
        print(f"❌ {msg}")
        print(f"   找过: {factor_dir}/daily_pv.h5")
        print(f"   找过: {round_dir}/daily_pv_debug.h5")
        print(f"   找过: {round_dir}/daily_pv.h5")
        return False, [msg]

    print(f"   数据文件: {debug_data}")

    # ── 1. 执行 factor.py ───────────────────────────────────
    print(f"🔄 执行 {factor_py.name} ...")
    if result_h5.exists():
        result_h5.unlink()

    try:
        env = os.environ.copy()
        env["DAILY_PV_PATH"] = str(debug_data)  # 传递数据文件路径给 factor.py
        output = subprocess.check_output(
            [sys.executable, str(factor_py)],
            cwd=str(factor_dir),
            stderr=subprocess.STDOUT,
            env=env,
            timeout=120,  # debug 数据 2 分钟应该够了
        )
        print(f"   执行输出 (末尾):\n   " + output.decode()[-500:].replace("\n", "\n   "))
    except subprocess.CalledProcessError as e:
        error_msg = e.output.decode()[-500:].strip()
        brief = error_msg.split("\n")[-1][:120]  # 取最后一行作为摘要
        print(f"❌ factor.py 执行失败:\n{error_msg}")
        return False, [f"factor.py 执行失败: {brief}"]
    except subprocess.TimeoutExpired:
        msg = "factor.py 执行超时 (>120秒)"
        print(f"❌ {msg}")
        return False, [msg]

    # ── 2. 检查 result.h5 是否生成 ──────────────────────────
    if not result_h5.exists():
        msg = "result.h5 未生成（factor.py 执行完毕但未输出文件）"
        print(f"❌ {msg}")
        return False, [msg]

    file_size = result_h5.stat().st_size
    if file_size == 0:
        msg = "result.h5 文件为空"
        print(f"❌ {msg}")
        return False, [msg]
    print(f"   result.h5 大小: {file_size / 1024:.1f} KB")

    # ── 3. 读取并验证格式 ───────────────────────────────────
    try:
        df = pd.read_hdf(result_h5, key="data")
    except Exception as e:
        msg = f"无法读取 result.h5: {e}"
        print(f"❌ {msg}")
        return False, [msg]

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
    # 动态 NaN 阈值：数据量越大允许 NaN 越少
    nan_threshold = 0.95 if total < 10000 else 0.80
    if null_ratio > nan_threshold:
        errors.append(f"NaN 比例过高: {null_ratio:.1%} (>{nan_threshold:.0%}）")
    print(f"   行数: {total}, 非空: {non_null}, NaN比例: {null_ratio:.1%}")

    # ── 4. 方差检查（全 0 的因子无区分度）───────────
    if len(df.columns) > 0:
        factor_vals = df.iloc[:, 0].dropna()
        if len(factor_vals) > 0:
            std_val = factor_vals.std()
            if std_val < 1e-8:
                errors.append(f"因子方差近于 0 (std={std_val:.2e})，因子全部相同无区分度")
            print(f"   均値: {factor_vals.mean():.4f}, 标准差: {std_val:.4f}")

            # ── 5. 极端値分布检查─────────────────────
            if std_val > 1e-8:
                z_scores = (factor_vals - factor_vals.mean()) / std_val
                extreme_ratio = (z_scores.abs() > 5).mean()
                if extreme_ratio > 0.05:
                    print(f"   ⚠️  |z-score|>5 的极端値比例: {extreme_ratio:.1%}（建议 clip/winsorize）")
                else:
                    print(f"   极端値比例 (|z|>5): {extreme_ratio:.1%}")

    # ── 6. 时间连续性检查───────────────────────
    dt_level = None
    if "datetime" in (df.index.names or []):
        dt_level = df.index.get_level_values("datetime")
        time_diffs = pd.Series(dt_level).diff().dropna().unique()

        # 拒绝分钟级
        if pd.Timedelta(minutes=1) in time_diffs:
            errors.append("检测到分钟级数据，因子应为日级")

        # 日期视为交易日，检查是否有大段空白（连续缺失 > 30 个交易日 ≈ 1.5 个月）
        unique_dates = pd.Series(dt_level).drop_duplicates().sort_values()
        if len(unique_dates) > 1:
            # 工作日间隔（跳过周末），超过 45 天认为异常间隔
            gaps = unique_dates.diff().dropna()
            max_gap = gaps.max()
            if max_gap > pd.Timedelta(days=45):
                print(f"   ⚠️  最大日期间隔: {max_gap.days} 天（可能有缺失交易日）")

    # ── 时间粒度检查（拒绝分钟级）──────────────
    # （已在上方处理，此处只保留一个占位以补全复数）
    # dt_level 已在上方赋値，后续用于打印范围

    # ── 汇总 ────────────────────────────────────────────────
    if errors:
        print(f"\n❌ 验证失败 ({len(errors)} 个问题):")
        for i, err in enumerate(errors, 1):
            print(f"   {i}. {err}")
        return False, errors
    else:
        print(f"\n\u2705 验证通过!")
        print(f"   因子: {list(df.columns)}")
        print(f"   形状: {df.shape}")
        if isinstance(df.index, pd.MultiIndex) and "datetime" in df.index.names and dt_level is not None:
            print(f"   时间: {dt_level.min()} ~ {dt_level.max()}")
            print(f"   股票: {df.index.get_level_values('instrument').nunique()}")
        return True, []


def _auto_record_error(factor_dir: Path, errors: list):
    """失败时自动调用 collect_error.py 记录错误到知识库"""
    # exp_root = factor_dir 的上上级（round_dir -> exp_root）
    exp_root = factor_dir.parent.parent
    collect_py = exp_root / "collect_error.py"
    if not collect_py.exists():
        return  # 知识库脚本不存在则跳过

    # 尝试从路径推断轮次号 (round_N -> N)
    round_dir = factor_dir.parent
    round_num = 0
    import re
    m = re.search(r"round[_\-]?(\d+)", round_dir.name, re.IGNORECASE)
    if m:
        round_num = int(m.group(1))

    error_summary = "; ".join(errors[:3])  # 取前 3 条错误合并为摘要
    try:
        import subprocess
        subprocess.run(
            [
                sys.executable, str(collect_py), "record",
                "--exp-root", str(exp_root),
                "--round", str(round_num),
                "--stage", "validate",
                "--factor", factor_dir.name,
                "--error", error_summary,
            ],
            check=False, capture_output=True,
        )
    except Exception:
        pass  # 记录失败不影响主流程


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python validate_factor.py <factor_dir>")
        sys.exit(1)
    result = validate(sys.argv[1])
    # validate() 返回 (bool, errors) 或旧版本的 bool
    if isinstance(result, tuple):
        ok, errors = result
    else:
        ok, errors = result, []
    # 失败时自动记录到错误知识库
    if not ok and errors:
        _auto_record_error(Path(sys.argv[1]).resolve(), errors)
    sys.exit(0 if ok else 1)
