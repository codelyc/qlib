#!/usr/bin/env python3
"""
Update Quant SOTA — 统一 SOTA 管理。

功能:
  - action=factor 且指标超越 SOTA → 更新 sota_combined.parquet
  - action=model 且指标超越 SOTA → 更新 current_sota_model.py + model_sota/ 备份
  - 更新统一 sota_record.json（含因子+模型联合指标）
  - 更新 quant_trace.json（记录本轮结果 + Bandit 学习）

用法:
    python update_quant_sota.py <exp_root> <round_dir> <round_num> <action>
"""

import json
import shutil
import sys
from pathlib import Path


def parse_metrics_from_csv(csv_path: Path) -> dict:
    """从 qlib_res.csv 解析指标."""
    metrics = {}
    if not csv_path.exists():
        return metrics
    try:
        with open(csv_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(",")
                if len(parts) >= 2:
                    key = parts[0].strip().lower().replace(" ", "_")
                    try:
                        val = float(parts[1].strip())
                        metrics[key] = val
                    except ValueError:
                        pass
    except Exception:
        pass
    return metrics


def compute_composite_score(metrics: dict) -> float:
    """计算综合评分 (对齐 fin-factor analyze_results.py)."""
    weights = {
        "ic": 0.10,
        "icir": 0.10,
        "rank_ic": 0.05,
        "rank_icir": 0.05,
        "annualized_return_rate": 0.25,
        "information_ratio": 0.15,
        "max_drawdown": 0.10,
        "sharpe": 0.20,
    }
    score = 0.0
    for key, weight in weights.items():
        val = metrics.get(key, 0.0)
        if key == "max_drawdown":
            val = -abs(val)  # 越小越好
        score += weight * val
    return score


def main():
    if len(sys.argv) < 5:
        print("用法: python update_quant_sota.py <exp_root> <round_dir> <round_num> <action>")
        sys.exit(1)

    exp_root = Path(sys.argv[1])
    round_dir = Path(sys.argv[2])
    round_num = int(sys.argv[3])
    action = sys.argv[4]

    sota_file = exp_root / "sota_record.json"

    # 读取现有 SOTA
    if sota_file.exists():
        sota = json.loads(sota_file.read_text())
    else:
        sota = {
            "round": 0,
            "factor_sota": {"factors": [], "metrics": None},
            "model_sota": {"model_name": None, "metrics": None},
            "combined_metrics": None,
            "history": [],
        }

    # 解析本轮指标
    csv_path = round_dir / "qlib_res.csv"
    metrics = parse_metrics_from_csv(csv_path)

    if not metrics:
        print(f"⚠️ round_{round_num} 无指标文件或为空: {csv_path}")
        return

    new_score = compute_composite_score(metrics)

    # 判断是否超越 SOTA
    sota_key = "factor_sota" if action == "factor" else "model_sota"
    old_metrics = sota.get(sota_key, {}).get("metrics")
    old_score = compute_composite_score(old_metrics) if old_metrics else float("-inf")

    is_new_sota = new_score > old_score
    decision = "✅ 超越 SOTA" if is_new_sota else "❌ 未超越 SOTA"
    print(f"{decision}: new={new_score:.6f} vs old={old_score:.6f}")

    if is_new_sota:
        if action == "factor":
            # 更新因子 SOTA
            sota["factor_sota"]["metrics"] = metrics

            # 复制 combined_factors_df.parquet → sota_combined.parquet
            combined_parquet = round_dir / "combined_factors_df.parquet"
            if combined_parquet.exists():
                shutil.copy2(
                    str(combined_parquet),
                    str(exp_root / "sota_combined.parquet"),
                )
                print("  📦 更新 sota_combined.parquet")

        elif action == "model":
            # 更新模型 SOTA
            sota["model_sota"]["metrics"] = metrics

            # 读取 model_meta.json
            meta_path = round_dir / "model_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                sota["model_sota"]["model_name"] = meta.get("model_name")
                sota["model_sota"]["model_type"] = meta.get("model_type")
                sota["model_sota"]["training_hyperparameters"] = meta.get(
                    "training_hyperparameters"
                )

            # 复制 model.py → current_sota_model.py + 备份
            model_py = round_dir / "model.py"
            if model_py.exists():
                shutil.copy2(
                    str(model_py), str(exp_root / "current_sota_model.py")
                )
                model_name = sota["model_sota"].get("model_name", "unknown")
                backup = exp_root / "model_sota" / f"round_{round_num}_{model_name}.py"
                shutil.copy2(str(model_py), str(backup))
                print(f"  📦 更新 current_sota_model.py (备份: {backup.name})")

        sota["round"] = round_num
        sota["combined_metrics"] = metrics

    # 记录历史 (含结构化反馈骨架，供 Agent 通过 quant_trace.py 补充)
    sota.setdefault("history", []).append(
        {
            "round": round_num,
            "action": action,
            "metrics": metrics,
            "score": new_score,
            "is_sota": is_new_sota,
            # Agent 应通过 quant_trace.py record 填写完整反馈
            "feedback": {
                "observations": decision,
                "hypothesis_evaluation": "",
                "new_hypothesis": "",
                "reasoning": "",
                "replace_sota": is_new_sota,
            },
            "concise_knowledge": "",
        }
    )

    # 保存
    sota_file.write_text(json.dumps(sota, indent=2, ensure_ascii=False))
    print(f"  💾 sota_record.json 已更新")

    # 同时更新 quant_trace（记录指标 + Bandit 学习）
    trace_updater = exp_root / ".." / ".." / ".github" / "skills" / "fin-quant" / "scripts" / "action_advisor.py"
    # 简化: 直接操作 quant_trace.json
    trace_file = exp_root / "quant_trace.json"
    if trace_file.exists():
        trace = json.loads(trace_file.read_text())
    else:
        trace = {"rounds": [], "bandit_state": {}}

    # 检查是否已记录（避免重复）
    existing_rounds = {r.get("round") for r in trace.get("rounds", [])}
    if round_num not in existing_rounds:
        trace.setdefault("rounds", []).append(
            {
                "round": round_num,
                "action": action,
                "metrics": metrics,
                "reward": new_score,
            }
        )
        trace_file.write_text(json.dumps(trace, indent=2, ensure_ascii=False))
        print(f"  📝 quant_trace.json 已更新")


if __name__ == "__main__":
    main()
