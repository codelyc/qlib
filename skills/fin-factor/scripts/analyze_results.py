#!/usr/bin/env python3
"""
回测结果分析脚本 — 解析 qlib_res.csv，与 SOTA 对比，输出结构化 JSON 报告。
借鉴: rdagent/scenarios/qlib/developer/feedback.py (process_results + comparison)

用法:
  python analyze_results.py <round_dir> [--sota-file <sota_record.json>]

产出:
  stdout — JSON 格式的分析报告
  $round_dir/analysis.json — 同内容持久化
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Qlib 回测输出中的关键指标 key（与 qlib_res.csv 中的行名对应）
METRIC_MAP = {
    "IC": {"display": "IC", "better": "higher", "threshold": 0.03},
    "ICIR": {"display": "ICIR", "better": "higher", "threshold": 0.3},
    "Rank IC": {"display": "Rank IC", "better": "higher", "threshold": 0.03},
    "Rank ICIR": {"display": "Rank ICIR", "better": "higher", "threshold": 0.3},
    "1day.excess_return_with_cost.annualized_return": {
        "display": "年化收益",
        "better": "higher",
        "threshold": 0.0,
    },
    "1day.excess_return_with_cost.max_drawdown": {
        "display": "最大回撤",
        "better": "higher",  # 回撤是负数，值越大（越接近0）越好
        "threshold": -0.20,
    },
    "1day.excess_return_with_cost.information_ratio": {
        "display": "夏普比率",
        "better": "higher",
        "threshold": 1.0,
    },
}


def load_metrics(qlib_res_path: Path) -> dict:
    """从 qlib_res.csv 加载指标"""
    df = pd.read_csv(qlib_res_path, index_col=0, header=None)
    metrics = {}
    for idx, row in df.iterrows():
        metrics[str(idx).strip()] = float(row.iloc[0])
    return metrics


def compare_metrics(current: dict, sota: dict | None) -> list[dict]:
    """对比当前结果与 SOTA"""
    comparisons = []
    for key, meta in METRIC_MAP.items():
        curr_val = None
        # 模糊匹配 key（qlib_res.csv 的 key 格式可能略有不同）
        for k, v in current.items():
            if key.lower() in k.lower() or meta["display"].lower() in k.lower():
                curr_val = v
                break

        if curr_val is None:
            continue

        sota_val = None
        if sota and "metrics" in sota and sota["metrics"]:
            for k, v in sota["metrics"].items():
                if key.lower() in k.lower() or meta["display"].lower() in k.lower():
                    sota_val = v
                    break

        improvement = None
        is_better = None
        if sota_val is not None:
            improvement = curr_val - sota_val
            if meta["better"] == "higher":
                is_better = improvement > 0
            else:
                is_better = improvement < 0

        comparisons.append(
            {
                "metric": meta["display"],
                "key": key,
                "current": round(curr_val, 6),
                "sota": round(sota_val, 6) if sota_val is not None else None,
                "improvement": round(improvement, 6) if improvement is not None else None,
                "is_better": is_better,
            }
        )

    return comparisons


def should_update_sota(comparisons: list[dict]) -> bool:
    """判断是否应该更新 SOTA — 借鉴 RD-Agent: 年化收益有任何正向提升即可"""
    for c in comparisons:
        if "年化收益" in c["metric"] or "annualized_return" in c["key"]:
            if c["improvement"] is not None and c["improvement"] > 0:
                return True
    # 如果没有 SOTA 可比，也算更新
    if all(c["sota"] is None for c in comparisons):
        return True
    return False


def analyze(round_dir: str, sota_file: str | None = None) -> dict:
    round_path = Path(round_dir).resolve()
    qlib_res = round_path / "qlib_res.csv"

    if not qlib_res.exists():
        return {"error": f"找不到 {qlib_res}"}

    # 加载当前结果
    current_metrics = load_metrics(qlib_res)

    # 加载 SOTA
    sota = None
    if sota_file and Path(sota_file).exists():
        with open(sota_file, "r") as f:
            sota = json.load(f)

    # 对比
    comparisons = compare_metrics(current_metrics, sota)
    update_sota = should_update_sota(comparisons)

    # 收集因子列表
    factors = []
    for sub_dir in sorted(round_path.iterdir()):
        if sub_dir.is_dir() and (sub_dir / "result.h5").exists():
            factors.append(sub_dir.name)

    report = {
        "round_dir": str(round_path),
        "factors": factors,
        "metrics": current_metrics,
        "comparisons": comparisons,
        "update_sota": update_sota,
        "sota_round": sota.get("round", 0) if sota else 0,
    }

    # 保存
    output_path = round_path / "analysis.json"
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


def print_report(report: dict):
    """人类可读的报告输出"""
    if "error" in report:
        print(f"❌ {report['error']}")
        return

    print("=" * 60)
    print("📊 回测结果分析")
    print("=" * 60)
    print(f"因子: {', '.join(report['factors'])}")
    print()

    print("指标对比:")
    print(f"  {'指标':<12} {'本轮':>12} {'SOTA':>12} {'变化':>12} {'判断':>6}")
    print(f"  {'-'*54}")
    for c in report["comparisons"]:
        curr = f"{c['current']:.4f}" if c["current"] is not None else "N/A"
        sota = f"{c['sota']:.4f}" if c["sota"] is not None else "N/A"
        imp = f"{c['improvement']:+.4f}" if c["improvement"] is not None else "N/A"
        flag = "✅" if c["is_better"] else ("❌" if c["is_better"] is False else "—")
        print(f"  {c['metric']:<12} {curr:>12} {sota:>12} {imp:>12} {flag:>6}")

    print()
    if report["update_sota"]:
        print("🏆 建议: 更新 SOTA")
    else:
        print("📉 建议: 不更新 SOTA")

    print(f"\n📄 详细 JSON 已保存: {report['round_dir']}/analysis.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析回测结果")
    parser.add_argument("round_dir", help="本轮工作目录")
    parser.add_argument("--sota-file", help="SOTA 记录 JSON 文件路径", default=None)
    args = parser.parse_args()

    report = analyze(args.round_dir, args.sota_file)
    print_report(report)

    # 也输出 JSON 到 stdout 供 Agent 解析
    print("\n--- JSON ---")
    print(json.dumps(report, indent=2, ensure_ascii=False))
