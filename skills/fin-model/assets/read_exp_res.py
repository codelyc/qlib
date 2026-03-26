"""
回测结果提取脚本 — 从 MLflow/Qlib 记录中提取关键回测指标

产出:
  qlib_res.csv — 回测指标（IC, ICIR, 年化收益, 最大回撤, 夏普等）
  ret.pkl      — 收益曲线数据
"""
import sys
from pathlib import Path

import os

import pandas as pd
import qlib

# MLFLOW_TRACKING_URI 从 .env 加载（本地运行时需要）
if "MLFLOW_TRACKING_URI" in os.environ:
    import mlflow
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

# qlib.init() 必须在使用 R 之前调用
# Docker 内 provider_uri 固定为 /qlib_data（由 -v 挂载）
qlib.init(provider_uri=os.environ.get("QLIB_PROVIDER_URI", "/qlib_data"), region="cn")

from qlib.workflow import R

# 列出所有实验，找到最新的 recorder
experiments = R.list_experiments()

experiment_name = None
latest_recorder = None
for experiment in experiments:
    recorders = R.list_recorders(experiment_name=experiment)
    for recorder_id in recorders:
        if recorder_id is not None:
            experiment_name = experiment
            recorder = R.get_recorder(recorder_id=recorder_id, experiment_name=experiment)
            end_time = recorder.info["end_time"]
            try:
                if end_time is not None:
                    if latest_recorder is None or end_time > latest_recorder.info["end_time"]:
                        latest_recorder = recorder
                else:
                    print(f"Warning: Recorder {recorder_id} has no valid end time")
            except Exception as e:
                print(f"Error: {e}")

if latest_recorder is None:
    print("❌ No recorders found — qrun may have failed silently")
    sys.exit(1)

print(f"Latest recorder: {latest_recorder}")

# 提取回测指标并保存
try:
    metrics = pd.Series(latest_recorder.list_metrics())
    output_path = Path(__file__).resolve().parent / "qlib_res.csv"
    metrics.to_csv(output_path)
    print(f"Output has been saved to {output_path}")
except Exception as e:
    print(f"❌ Failed to extract metrics: {e}")
    sys.exit(1)

# 提取收益曲线数据
try:
    ret_data_frame = latest_recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    ret_data_frame.to_pickle("ret.pkl")
    print("Return data saved to ret.pkl")
except Exception as e:
    print(f"⚠️ Failed to extract return data (ret.pkl): {e}")
    # Not fatal — qlib_res.csv is the primary output
