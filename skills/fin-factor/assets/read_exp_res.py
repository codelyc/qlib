"""
回测结果提取脚本
从 MLflow/Qlib 记录中提取关键回测指标，输出到 qlib_res.csv 和 ret.pkl
"""
import pickle
from pathlib import Path

import pandas as pd
import qlib
from mlflow.entities import ViewType
from mlflow.tracking import MlflowClient

qlib.init()

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
    print("No recorders found")
else:
    print(f"Latest recorder: {latest_recorder}")

    # 提取回测指标并保存
    metrics = pd.Series(latest_recorder.list_metrics())
    output_path = Path(__file__).resolve().parent / "qlib_res.csv"
    metrics.to_csv(output_path)
    print(f"Output has been saved to {output_path}")

    # 提取收益曲线数据
    ret_data_frame = latest_recorder.load_object("portfolio_analysis/report_normal_1day.pkl")
    ret_data_frame.to_pickle("ret.pkl")
    print("Return data saved to ret.pkl")
