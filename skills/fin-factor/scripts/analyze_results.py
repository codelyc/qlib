#!/usr/bin/env python3
"""
回测结果分析脚本 — 解析 qlib_res.csv，与 SOTA 对比，输出结构化 JSON 报告。
借鉴: rdagent/scenarios/qlib/developer/feedback.py (process_results + comparison)

用法:
  # 合并回测分析（默认模式）
  python analyze_results.py <round_dir> [--sota-file <sota_record.json>]

  # 单因子回测分析
  python analyze_results.py <round_dir> --factor-dir <factor_name> [--sota-file ...]

产出:
  stdout — JSON 格式的分析报告
  $round_dir/analysis.json — 同内容持久化（合并模式含 single_factor_results 汇总）
  $round_dir/$factor_name/analysis.json — 单因子分析结果
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

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


def _find_metric_value(key: str, display: str, data: dict):
    """在 data 中查找指标值：优先精确匹配 key，再精确匹配 display，最后才模糊匹配。"""
    # 1) 精确匹配 key
    if key in data:
        return data[key]
    # 2) 精确匹配 display name
    if display in data:
        return data[display]
    # 3) 大小写不敏感的精确匹配
    key_lower = key.lower()
    display_lower = display.lower()
    for k, v in data.items():
        if k.lower() == key_lower or k.lower() == display_lower:
            return v
    # 4) 最后才用子串模糊匹配，但加长度约束避免短 key 误匹配长 key
    #    例如搜 "IC"(len=2) 不应该匹配到 "Rank IC"(len=7)
    for k, v in data.items():
        if (key_lower in k.lower() and len(key) >= len(k)) or \
           (display_lower in k.lower() and len(display) >= len(k)):
            return v
    return None


def compare_metrics(current: dict, sota: Optional[dict]) -> List[dict]:
    """对比当前结果与 SOTA"""
    comparisons = []
    for key, meta in METRIC_MAP.items():
        curr_val = _find_metric_value(key, meta["display"], current)

        if curr_val is None:
            continue

        sota_val = None
        if sota:
            sota_metrics = sota.get("sota_metrics") or sota.get("metrics")
            if sota_metrics:
                sota_val = _find_metric_value(key, meta["display"], sota_metrics)

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


def should_update_sota(comparisons: List[dict]) -> bool:
    """
    多指标综合评分决定是否更新 SOTA。
    权重: IC 25% + ICIR 10% + Rank IC 25% + Rank ICIR 10% + 年化收益 15% + 夏普 15%
    只有综合分 > 0（且至少 2 个关键指标改善）才更新。
    """
    # 如果没有 SOTA 可比（首轮），直接更新
    if all(c["sota"] is None for c in comparisons):
        return True

    # 加权评分
    weights = {
        "IC": 0.25,
        "Rank IC": 0.25,
        "ICIR": 0.10,
        "Rank ICIR": 0.10,
        "年化收益": 0.15,
        "夏普比率": 0.15,
    }
    weighted_score = 0.0
    total_weight = 0.0
    better_count = 0
    worse_count = 0

    for c in comparisons:
        w = weights.get(c["metric"], 0.0)
        if w == 0 or c["improvement"] is None:
            continue
        # 归一化改善值（避免量纲不同的指标主导评分）
        # 用 |sota| 作为归一化基准（避免除以 0）
        base = abs(c["sota"]) if c["sota"] and abs(c["sota"]) > 1e-8 else 1.0
        normalized = c["improvement"] / base
        weighted_score += w * normalized
        total_weight += w
        if c["is_better"]:
            better_count += 1
        else:
            worse_count += 1

    if total_weight == 0:
        return False

    weighted_score /= total_weight  # 归一化到 [-1, 1] 范围

    # 决策：综合分 > 0 且至少 2 个指标改善
    decision = weighted_score > 0 and better_count >= 2
    return decision


def compute_composite_score(comparisons: List[dict]) -> float:
    """计算综合评分（供报告展示）"""
    weights = {
        "IC": 0.25, "Rank IC": 0.25, "ICIR": 0.10, "Rank ICIR": 0.10,
        "年化收益": 0.15, "夏普比率": 0.15,
    }
    score = 0.0
    total_w = 0.0
    for c in comparisons:
        w = weights.get(c["metric"], 0.0)
        if w == 0 or c["improvement"] is None:
            continue
        base = abs(c["sota"]) if c["sota"] and abs(c["sota"]) > 1e-8 else 1.0
        score += w * (c["improvement"] / base)
        total_w += w
    return round(score / total_w, 6) if total_w > 0 else 0.0


def collect_single_factor_results(round_path: Path) -> List[dict]:
    """扫描 round_dir 下所有因子子目录的 analysis.json，汇总单因子回测结果"""
    results = []
    for sub_dir in sorted(round_path.iterdir()):
        if not sub_dir.is_dir():
            continue
        analysis_file = sub_dir / "analysis.json"
        if not analysis_file.exists():
            continue
        try:
            with open(analysis_file, "r") as f:
                data = json.load(f)
            # 提取关键指标
            metrics = data.get("metrics", {})
            summary = {
                "factor": sub_dir.name,
                "IC": metrics.get("IC"),
                "ICIR": metrics.get("ICIR"),
                "Rank IC": metrics.get("Rank IC"),
                "Rank ICIR": metrics.get("Rank ICIR"),
                "annualized_return": metrics.get(
                    "1day.excess_return_with_cost.annualized_return"
                ),
                "max_drawdown": metrics.get(
                    "1day.excess_return_with_cost.max_drawdown"
                ),
                "sharpe": metrics.get(
                    "1day.excess_return_with_cost.information_ratio"
                ),
                "composite_score": data.get("composite_score"),
                "update_sota": data.get("update_sota"),
            }
            results.append(summary)
        except Exception as e:
            print(f"  ⚠️ 读取 {analysis_file} 失败: {e}")
    return results


def analyze(
    round_dir: str,
    sota_file: Optional[str] = None,
    baseline_file: Optional[str] = None,
    factor_dir: Optional[str] = None,
) -> dict:
    round_path = Path(round_dir).resolve()

    # 单因子模式：分析因子子目录中的 qlib_res.csv
    if factor_dir:
        target_path = round_path / factor_dir
        qlib_res = target_path / "qlib_res.csv"
    else:
        target_path = round_path
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

    # 加载静态基线
    baseline = None
    baseline_comparisons = []
    if baseline_file and Path(baseline_file).exists():
        with open(baseline_file, "r") as f:
            baseline = json.load(f)
        baseline_comparisons = compare_metrics(
            current_metrics, {"metrics": baseline.get("metrics", {})}
        )

    # 对比 (vs SOTA)
    comparisons = compare_metrics(current_metrics, sota)
    update_sota = should_update_sota(comparisons)
    composite_score = compute_composite_score(comparisons)

    # 收集因子列表
    factors = []
    if factor_dir:
        factors = [factor_dir]
    else:
        for sub_dir in sorted(round_path.iterdir()):
            if sub_dir.is_dir() and (sub_dir / "result.h5").exists():
                factors.append(sub_dir.name)

    # 生成简短的决策说明（供 Agent 理解）
    better_metrics = [c["metric"] for c in comparisons if c.get("is_better")]
    worse_metrics = [c["metric"] for c in comparisons if c.get("is_better") is False]
    decision_reason = (
        f"综合评分 {composite_score:+.4f}，"
        f"{len(better_metrics)} 项改善 ({', '.join(better_metrics) or '无'})，"
        f"{len(worse_metrics)} 项下降 ({', '.join(worse_metrics) or '无'})"
    )

    report = {
        "round_dir": str(target_path),
        "factors": factors,
        "metrics": current_metrics,
        "comparisons": comparisons,
        "baseline_comparison": baseline_comparisons,
        "composite_score": composite_score,
        "update_sota": update_sota,
        "decision_reason": decision_reason,
        "sota_round": sota.get("round", 0) if sota else 0,
    }

    # 合并模式时，汇总单因子独立回测结果
    if not factor_dir:
        single_results = collect_single_factor_results(round_path)
        if single_results:
            report["single_factor_results"] = single_results

    # 保存
    output_path = target_path / "analysis.json"
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

    # Baseline 对比（如果有）
    baseline_comps = report.get("baseline_comparison", [])
    if baseline_comps:
        print()
        print("vs 静态基线 (Alpha158):")
        print(f"  {'指标':<12} {'本轮':>12} {'Baseline':>12} {'vs基线':>12}")
        print(f"  {'-'*48}")
        for c in baseline_comps:
            curr = f"{c['current']:.4f}" if c["current"] is not None else "N/A"
            base = f"{c['sota']:.4f}" if c["sota"] is not None else "N/A"
            imp = f"{c['improvement']:+.4f}" if c["improvement"] is not None else "N/A"
            print(f"  {c['metric']:<12} {curr:>12} {base:>12} {imp:>12}")

    # 单因子汇总（如果有）
    single_results = report.get("single_factor_results", [])
    if single_results:
        print()
        print("📋 单因子独立回测汇总:")
        print(f"  {'因子':<25} {'IC':>8} {'ICIR':>8} {'年化收益':>10} {'夏普':>8} {'综合分':>8}")
        print(f"  {'-'*67}")
        for sr in single_results:
            name = sr.get('factor', '?')[:24]
            ic = f"{sr['IC']:.4f}" if sr.get('IC') is not None else 'N/A'
            icir = f"{sr['ICIR']:.4f}" if sr.get('ICIR') is not None else 'N/A'
            ar = f"{sr['annualized_return']:.4f}" if sr.get('annualized_return') is not None else 'N/A'
            sp = f"{sr['sharpe']:.4f}" if sr.get('sharpe') is not None else 'N/A'
            cs = f"{sr['composite_score']:+.4f}" if sr.get('composite_score') is not None else 'N/A'
            print(f"  {name:<25} {ic:>8} {icir:>8} {ar:>10} {sp:>8} {cs:>8}")

    print()
    score = report.get("composite_score", 0)
    reason = report.get("decision_reason", "")
    print(f"综合评分: {score:+.4f}  ({reason})")
    print()
    if report["update_sota"]:
        print("🏆 建议: 更新 SOTA ✅")
    else:
        print("📉 建议: 不更新 SOTA（改善不足或关键指标下降）")

    print(f"\n📄 详细 JSON 已保存: {report['round_dir']}/analysis.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析回测结果")
    parser.add_argument("round_dir", help="本轮工作目录")
    parser.add_argument("--sota-file", help="SOTA 记录 JSON 文件路径", default=None)
    parser.add_argument("--baseline-file", help="静态基线记录 (baseline_record.json)", default=None)
    parser.add_argument(
        "--factor-dir",
        metavar="FACTOR_NAME",
        help="单因子模式：分析因子子目录中的 qlib_res.csv",
        default=None,
    )
    args = parser.parse_args()

    report = analyze(args.round_dir, args.sota_file, args.baseline_file, args.factor_dir)
    print_report(report)

    # 也输出 JSON 到 stdout 供 Agent 解析
    print("\n--- JSON ---")
    print(json.dumps(report, indent=2, ensure_ascii=False))
