#!/usr/bin/env python3
"""
更新 SOTA 记录 — 根据 analysis.json 更新 sota_record.json 和 sota_combined.parquet。
借鉴: rdagent/scenarios/qlib/developer/factor_runner.py (SOTA factor accumulation)

用法:
  python update_sota.py <exp_root> <round_dir> <round_number>

做的事:
  1. 读取 $round_dir/analysis.json 判断是否需要更新
  2. 如果需要，把本轮的 combined_factors_df.parquet 复制为新的 SOTA
  3. 更新 $exp_root/sota_record.json
"""
import json
import shutil
import sys
from pathlib import Path


def update_sota(exp_root: str, round_dir: str, round_number: int):
    exp_root_path = Path(exp_root).resolve()
    round_path = Path(round_dir).resolve()

    analysis_file = round_path / "analysis.json"
    sota_record_file = exp_root_path / "sota_record.json"
    sota_parquet_file = exp_root_path / "sota_combined.parquet"
    round_parquet = round_path / "combined_factors_df.parquet"

    # 读取分析结果
    if not analysis_file.exists():
        print(f"❌ 找不到 {analysis_file}，请先运行 analyze_results.py")
        return False

    with open(analysis_file, "r") as f:
        analysis = json.load(f)

    # 读取现有 SOTA 记录
    if sota_record_file.exists():
        with open(sota_record_file, "r") as f:
            sota = json.load(f)
    else:
        sota = {"round": 0, "sota_factors": [], "sota_metrics": None, "history": []}

    # 记录到历史
    history_entry = {
        "round": round_number,
        "factors": analysis.get("factors", []),
        "update_sota": analysis.get("update_sota", False),
        "metrics_summary": {},
    }
    for c in analysis.get("comparisons", []):
        history_entry["metrics_summary"][c["metric"]] = c["current"]
    sota["history"].append(history_entry)

    # 判断是否更新 SOTA
    if analysis.get("update_sota", False):
        print(f"🏆 更新 SOTA (第 {round_number} 轮)")

        # 更新 parquet
        if round_parquet.exists():
            shutil.copy2(round_parquet, sota_parquet_file)
            print(f"  ✅ sota_combined.parquet 已更新")
        else:
            print(f"  ⚠️ {round_parquet} 不存在，跳过 parquet 更新")

        # 更新记录
        sota["round"] = round_number
        sota["sota_factors"] = analysis.get("factors", [])
        sota["sota_metrics"] = {}
        for c in analysis.get("comparisons", []):
            sota["sota_metrics"][c["key"]] = c["current"]

        print(f"  ✅ SOTA 因子: {sota['sota_factors']}")
    else:
        print(f"📉 第 {round_number} 轮未超越 SOTA，不更新")

    # 保存 SOTA 记录
    with open(sota_record_file, "w") as f:
        json.dump(sota, f, indent=2, ensure_ascii=False)
    print(f"  ✅ sota_record.json 已更新")

    return analysis.get("update_sota", False)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python update_sota.py <exp_root> <round_dir> <round_number>")
        sys.exit(1)

    updated = update_sota(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    sys.exit(0)
