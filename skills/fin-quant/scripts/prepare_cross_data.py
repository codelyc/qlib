#!/usr/bin/env python3
"""
Cross-Data Preparer — 交叉集成数据准备。

参考: RD-Agent/rdagent/scenarios/qlib/developer/model_runner.py
      process_factor_data() + develop() 中的 SOTA 因子注入逻辑

功能:
  action=model 时:
    - 复制 $QUANT_EXP_ROOT/sota_combined.parquet → $ROUND_DIR/combined_factors_df.parquet
    - 计算 num_features = base_features + SOTA_factor_columns
    - 输出选择的配置文件名

  action=factor + SOTA 模型存在时:
    - 复制 $QUANT_EXP_ROOT/current_sota_model.py → $ROUND_DIR/model.py
    - 输出选择的配置文件名

用法:
    python prepare_cross_data.py --exp-root /path --round-dir /path/round_1 --action model
    python prepare_cross_data.py --exp-root /path --round-dir /path/round_1 --action factor
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd


def prepare_for_model(exp_root: Path, round_dir: Path, base_feature_count: int) -> dict:
    """模型回测前: 注入 SOTA 因子."""
    sota_parquet = exp_root / "sota_combined.parquet"
    result = {
        "config": "conf_baseline_model.yaml",
        "has_sota_factors": False,
        "num_features": base_feature_count,
    }

    if sota_parquet.exists():
        target = round_dir / "combined_factors_df.parquet"
        shutil.copy2(str(sota_parquet), str(target))

        # 计算总特征数
        try:
            df = pd.read_parquet(str(sota_parquet))
            if hasattr(df.columns, "levels"):
                # MultiIndex columns
                n_sota = len(df.columns.get_level_values(-1).unique())
            else:
                n_sota = len(df.columns)
            result["num_features"] = base_feature_count + n_sota
        except Exception as e:
            print(f"⚠️ 读取 SOTA 因子 parquet 失败: {e}", file=sys.stderr)
            result["num_features"] = base_feature_count

        result["config"] = "conf_sota_model.yaml"
        result["has_sota_factors"] = True
        print(f"✅ 已注入 SOTA 因子 → {target.name} (特征数: {result['num_features']})")
    else:
        print("ℹ️  无 SOTA 因子文件，模型将使用基础特征 (Alpha20/158)")

    return result


def prepare_for_factor(exp_root: Path, round_dir: Path) -> dict:
    """因子回测前: 注入 SOTA 模型 (可选)."""
    sota_model = exp_root / "current_sota_model.py"
    result = {
        "config_lgbm": "conf_combined_factors.yaml",
        "config_ptnn": "conf_factor_with_sota_model.yaml",
        "has_sota_model": False,
    }

    if sota_model.exists():
        target = round_dir / "model.py"
        shutil.copy2(str(sota_model), str(target))
        result["has_sota_model"] = True
        print(f"✅ 已注入 SOTA 模型 → {target.name}")
        print("   因子将用 LightGBM + SOTA 模型双评估")
    else:
        print("ℹ️  无 SOTA 模型，因子评估仅使用 LightGBM")

    return result


def main():
    parser = argparse.ArgumentParser(description="交叉集成数据准备")
    parser.add_argument("--exp-root", required=True, help="工作区路径")
    parser.add_argument("--round-dir", required=True, help="当前轮次目录")
    parser.add_argument("--action", choices=["factor", "model"], required=True)
    parser.add_argument(
        "--base-features",
        type=int,
        default=20,
        help="基础特征数 (Alpha20=20, Alpha158=158)",
    )
    args = parser.parse_args()

    exp_root = Path(args.exp_root)
    round_dir = Path(args.round_dir)

    if not round_dir.exists():
        round_dir.mkdir(parents=True)

    if args.action == "model":
        result = prepare_for_model(exp_root, round_dir, args.base_features)
    else:
        result = prepare_for_factor(exp_root, round_dir)

    # 输出 JSON 到 stdout（供 shell 脚本解析）
    print("---JSON---")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
