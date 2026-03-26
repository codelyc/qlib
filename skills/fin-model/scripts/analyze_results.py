#!/usr/bin/env python3
"""
模型回测结果分析脚本 — 解析 qlib_res.csv + 训练日志，与 SOTA 对比。
来源: fin-factor analyze_results.py + RD-Agent feedback.py IMPORTANT_METRICS

用法:
  python analyze_results.py <round_dir> [--sota-file <sota_record.json>]

产出:
  $round_dir/analysis.json — 结构化分析报告（含训练日志摘要）
"""
import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Optional

import pandas as pd

# 关键指标（对齐 RD-Agent feedback.py IMPORTANT_METRICS）
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
        "better": "higher",
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
    """在 data 中查找指标值"""
    if key in data:
        return data[key]
    if display in data:
        return data[display]
    key_lower = key.lower()
    display_lower = display.lower()
    for k, v in data.items():
        if k.lower() == key_lower or k.lower() == display_lower:
            return v
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
            is_better = improvement > 0 if meta["better"] == "higher" else improvement < 0

        comparisons.append({
            "metric": meta["display"],
            "key": key,
            "current": round(curr_val, 6),
            "sota": round(sota_val, 6) if sota_val is not None else None,
            "improvement": round(improvement, 6) if improvement is not None else None,
            "is_better": is_better,
        })
    return comparisons


def should_update_sota(comparisons: List[dict]) -> bool:
    """
    决定是否更新 SOTA。
    对齐 RD-Agent feedback.py 逻辑:
      - 年化收益改善 → 推荐替换
      - 其他指标小幅波动可接受
      - 首轮无 SOTA → 直接更新（只要 ICIR > 0）
    """
    if all(c["sota"] is None for c in comparisons):
        # 首轮：只要 ICIR > 0 就接受
        for c in comparisons:
            if c["metric"] == "ICIR" and c["current"] is not None:
                return c["current"] > 0
        return True

    # 权重评分
    weights = {
        "IC": 0.20, "Rank IC": 0.20, "ICIR": 0.10, "Rank ICIR": 0.10,
        "年化收益": 0.25, "夏普比率": 0.15,
    }
    weighted_score = 0.0
    total_weight = 0.0
    better_count = 0

    for c in comparisons:
        w = weights.get(c["metric"], 0.0)
        if w == 0 or c["improvement"] is None:
            continue
        base = abs(c["sota"]) if c["sota"] and abs(c["sota"]) > 1e-8 else 1.0
        weighted_score += w * (c["improvement"] / base)
        total_weight += w
        if c["is_better"]:
            better_count += 1

    if total_weight == 0:
        return False

    weighted_score /= total_weight
    return weighted_score > 0 and better_count >= 2


def compute_composite_score(comparisons: List[dict]) -> float:
    """计算综合评分"""
    weights = {
        "IC": 0.20, "Rank IC": 0.20, "ICIR": 0.10, "Rank ICIR": 0.10,
        "年化收益": 0.25, "夏普比率": 0.15,
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


def analyze_training_log(round_dir: Path) -> dict:
    """
    分析 Docker 训练日志 — 对齐 RD-Agent feedback.py Training Log 分析。
    从 docker_run.log 提取:
      - Early stopping 轮次
      - Loss 趋势 (training/validation)
      - 训练时间
      - 过拟合检测
    """
    log_file = round_dir / "docker_run.log"
    analysis = {
        "early_stopping_round": None,
        "total_epochs": None,
        "train_loss_final": None,
        "valid_loss_final": None,
        "overfitting_detected": False,
        "training_time_seconds": None,
        "warnings": [],
        "raw_excerpts": [],
    }

    if not log_file.exists():
        analysis["warnings"].append("docker_run.log 不存在")
        return analysis

    log_text = log_file.read_text(errors="replace")

    # Early stopping
    es_match = re.search(r"early stop(?:ping)?.*?(?:round|epoch)\s*(\d+)", log_text, re.IGNORECASE)
    if es_match:
        analysis["early_stopping_round"] = int(es_match.group(1))

    # Epoch 数
    epoch_matches = re.findall(r"(?:Epoch|epoch)\s*(\d+)", log_text)
    if epoch_matches:
        analysis["total_epochs"] = max(int(e) for e in epoch_matches)

    # Loss 值
    train_losses = re.findall(r"train.*?(?:loss|mse)[:\s]+([0-9.e-]+)", log_text, re.IGNORECASE)
    valid_losses = re.findall(r"valid.*?(?:loss|mse)[:\s]+([0-9.e-]+)", log_text, re.IGNORECASE)
    if train_losses:
        analysis["train_loss_final"] = float(train_losses[-1])
    if valid_losses:
        analysis["valid_loss_final"] = float(valid_losses[-1])

    # 过拟合检测: valid loss 明显高于 train loss
    if analysis["train_loss_final"] and analysis["valid_loss_final"]:
        ratio = analysis["valid_loss_final"] / (analysis["train_loss_final"] + 1e-12)
        if ratio > 1.5:
            analysis["overfitting_detected"] = True
            analysis["warnings"].append(
                f"疑似过拟合: valid_loss/train_loss = {ratio:.2f}"
            )

    # Early stopping 过早
    if analysis["early_stopping_round"] and analysis["early_stopping_round"] < 30:
        analysis["warnings"].append(
            f"Early stopping 仅 {analysis['early_stopping_round']} 轮，可能 lr 过高或模型不稳定"
        )

    # 训练时间
    time_match = re.search(r"(?:Time|time|用时)[:\s]+(\d+(?:\.\d+)?)\s*(?:s|sec|秒)", log_text)
    if time_match:
        analysis["training_time_seconds"] = float(time_match.group(1))

    # 提取关键日志片段（最后 10 行含 loss/metric 的行）
    key_lines = [
        line.strip() for line in log_text.split("\n")
        if re.search(r"loss|mse|early|metric|IC|valid|train", line, re.IGNORECASE)
    ]
    analysis["raw_excerpts"] = key_lines[-10:]

    return analysis


def analyze(round_dir: str, sota_file: Optional[str] = None) -> dict:
    round_path = Path(round_dir).resolve()
    qlib_res = round_path / "qlib_res.csv"

    if not qlib_res.exists():
        return {"error": f"找不到 {qlib_res}"}

    current_metrics = load_metrics(qlib_res)

    # 加载 SOTA
    sota = None
    if sota_file and Path(sota_file).exists():
        with open(sota_file, "r") as f:
            sota = json.load(f)

    # 对比
    comparisons = compare_metrics(current_metrics, sota)
    update_sota = should_update_sota(comparisons)
    composite_score = compute_composite_score(comparisons)

    # 训练日志分析（模型优化特有）
    training_analysis = analyze_training_log(round_path)

    # 决策说明
    better_metrics = [c["metric"] for c in comparisons if c.get("is_better")]
    worse_metrics = [c["metric"] for c in comparisons if c.get("is_better") is False]
    decision_reason = (
        f"综合评分 {composite_score:+.4f}，"
        f"{len(better_metrics)} 项改善 ({', '.join(better_metrics) or '无'})，"
        f"{len(worse_metrics)} 项下降 ({', '.join(worse_metrics) or '无'})"
    )

    # 模型信息
    model_meta = {}
    meta_file = round_path / "model_meta.json"
    if meta_file.exists():
        with open(meta_file, "r") as f:
            model_meta = json.load(f)

    report = {
        "round_dir": str(round_path),
        "model_name": model_meta.get("model_name", "unknown"),
        "model_type": model_meta.get("model_type", "unknown"),
        "metrics": current_metrics,
        "comparisons": comparisons,
        "composite_score": composite_score,
        "update_sota": update_sota,
        "decision_reason": decision_reason,
        "training_analysis": training_analysis,
        "sota_round": sota.get("round", 0) if sota else 0,
    }

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
    print("📊 模型回测结果分析")
    print("=" * 60)
    print(f"模型: {report.get('model_name', 'unknown')} ({report.get('model_type', 'unknown')})")
    print()

    # 指标对比
    print("指标对比:")
    print(f"  {'指标':<12} {'本轮':>12} {'SOTA':>12} {'变化':>12} {'判断':>6}")
    print(f"  {'-'*54}")
    for c in report["comparisons"]:
        curr = f"{c['current']:.4f}" if c["current"] is not None else "N/A"
        sota = f"{c['sota']:.4f}" if c["sota"] is not None else "N/A"
        imp = f"{c['improvement']:+.4f}" if c["improvement"] is not None else "N/A"
        flag = "✅" if c["is_better"] else ("❌" if c["is_better"] is False else "—")
        print(f"  {c['metric']:<12} {curr:>12} {sota:>12} {imp:>12} {flag:>6}")

    # 训练日志摘要
    ta = report.get("training_analysis", {})
    if ta:
        print()
        print("🔍 训练日志分析:")
        if ta.get("early_stopping_round"):
            print(f"  Early stopping: 第 {ta['early_stopping_round']} 轮")
        if ta.get("total_epochs"):
            print(f"  总训练轮次: {ta['total_epochs']}")
        if ta.get("train_loss_final"):
            print(f"  最终 train loss: {ta['train_loss_final']:.6f}")
        if ta.get("valid_loss_final"):
            print(f"  最终 valid loss: {ta['valid_loss_final']:.6f}")
        if ta.get("overfitting_detected"):
            print(f"  ⚠️ 过拟合检测: 是")
        for w in ta.get("warnings", []):
            print(f"  ⚠️ {w}")

    # 综合评分
    print()
    score = report.get("composite_score", 0)
    reason = report.get("decision_reason", "")
    print(f"综合评分: {score:+.4f}  ({reason})")
    print()
    if report["update_sota"]:
        print("🏆 建议: 更新 SOTA ✅")
    else:
        print("📉 建议: 不更新 SOTA")

    print(f"\n📄 详细 JSON 已保存: {report['round_dir']}/analysis.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析模型回测结果")
    parser.add_argument("round_dir", help="本轮工作目录")
    parser.add_argument("--sota-file", help="SOTA 记录 JSON 文件路径", default=None)
    args = parser.parse_args()

    report = analyze(args.round_dir, args.sota_file)
    print_report(report)

    print("\n--- JSON ---")
    print(json.dumps(report, indent=2, ensure_ascii=False))
