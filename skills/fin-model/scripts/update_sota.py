#!/usr/bin/env python3
"""
更新 SOTA 记录 — 根据 analysis.json 更新 sota_record.json + 备份 model.py。
来源: fin-factor update_sota.py + RD-Agent SOTA 追踪逻辑

用法:
  python update_sota.py <exp_root> <round_dir> <round_number>

做的事:
  1. 读取 $round_dir/analysis.json 判断是否需要更新
  2. 如果需要，备份 model.py 到 model_sota/round_N_model.py
  3. 更新 $exp_root/sota_record.json（含 model_name, model_type, training_hyperparameters）
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
    model_py = round_path / "model.py"
    model_meta_file = round_path / "model_meta.json"
    model_sota_dir = exp_root_path / "model_sota"

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
        sota = {
            "round": 0, "model_name": None, "model_type": None,
            "sota_metrics": None, "training_hyperparameters": None,
            "history": [],
        }

    # 读取模型元信息
    model_meta = {}
    if model_meta_file.exists():
        with open(model_meta_file, "r") as f:
            model_meta = json.load(f)

    # 记录到历史 (含结构化反馈，供 fin-quant 聚合)
    history_entry = {
        "round": round_number,
        "model_name": analysis.get("model_name", model_meta.get("model_name", "unknown")),
        "model_type": analysis.get("model_type", model_meta.get("model_type", "unknown")),
        "update_sota": analysis.get("update_sota", False),
        "metrics_summary": {},
        "training_analysis": {
            "early_stopping_round": analysis.get("training_analysis", {}).get("early_stopping_round"),
            "overfitting_detected": analysis.get("training_analysis", {}).get("overfitting_detected"),
        },
        # 结构化反馈 (对齐 RD-Agent HypothesisFeedback + fin-quant feedback-format)
        "feedback": {
            "observations": analysis.get("decision_reason", ""),
            "hypothesis_evaluation": "",  # Agent 填写
            "new_hypothesis": "",         # Agent 填写
            "reasoning": "",              # Agent 填写
            "replace_sota": analysis.get("update_sota", False),
        },
        "concise_knowledge": "",  # Agent 每轮填写核心洞察
    }
    for c in analysis.get("comparisons", []):
        history_entry["metrics_summary"][c["metric"]] = c["current"]
    sota["history"].append(history_entry)

    # 判断是否更新 SOTA
    if analysis.get("update_sota", False):
        print(f"🏆 更新 SOTA (第 {round_number} 轮)")

        # 备份 model.py
        model_sota_dir.mkdir(parents=True, exist_ok=True)
        if model_py.exists():
            backup_name = f"round_{round_number}_{model_meta.get('model_name', 'model')}.py"
            shutil.copy2(model_py, model_sota_dir / backup_name)
            # 同时保存一份当前 SOTA 版本（方便下一轮参考）
            shutil.copy2(model_py, model_sota_dir / "current_sota_model.py")
            print(f"  ✅ model.py → model_sota/{backup_name}")
        else:
            print(f"  ⚠️ {model_py} 不存在，跳过备份")

        # 备份 model_meta.json
        if model_meta_file.exists():
            shutil.copy2(model_meta_file, model_sota_dir / "current_sota_meta.json")

        # 更新记录
        sota["round"] = round_number
        sota["model_name"] = model_meta.get("model_name", analysis.get("model_name"))
        sota["model_type"] = model_meta.get("model_type", analysis.get("model_type"))
        sota["training_hyperparameters"] = model_meta.get("training_hyperparameters")
        sota["sota_metrics"] = {}
        for c in analysis.get("comparisons", []):
            sota["sota_metrics"][c["key"]] = c["current"]

        print(f"  ✅ SOTA 模型: {sota['model_name']} ({sota['model_type']})")
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
