#!/usr/bin/env python3
"""
模型代码快速验证脚本 — 通过 dummy forward pass (<30秒) 验证 model.py 是否正确。
来源: RD-Agent/rdagent/components/coder/model_coder/model_execute_template_v1.txt

用法:
  python validate_model.py <model_dir>

model_dir 需包含:
  - model.py        — PyTorch 模型代码（必须导出 model_cls）
  - model_meta.json — 模型元信息（可选，默认 TimeSeries）

验证项:
  1. model.py 能否导入成功（from model import model_cls）
  2. model_cls 是否为 torch.nn.Module 子类
  3. forward pass 是否执行成功（dummy input）
  4. 输出 shape 是否为 (batch_size, 1)
  5. 输出是否包含 NaN/Inf
  6. 参数数量检查（>100M 警告）

退出码: 0=通过, 1=失败
"""
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

# ── 全局配置（对齐 RD-Agent model_execute_template_v1.txt）──
BATCH_SIZE = 8
DEFAULT_NUM_FEATURES = 20
DEFAULT_NUM_TIMESTEPS = 20
INPUT_VALUE = 1.0
PARAM_INIT_VALUE = 1.0
TIMEOUT_SEC = 60


def load_model_meta(model_dir: Path) -> dict:
    """从 model_meta.json 加载模型元信息"""
    meta_file = model_dir / "model_meta.json"
    if meta_file.exists():
        with open(meta_file, "r") as f:
            return json.load(f)
    # 默认 TimeSeries
    return {
        "model_type": "TimeSeries",
        "num_features": int(os.environ.get("num_features", DEFAULT_NUM_FEATURES)),
        "num_timesteps": int(os.environ.get("num_timesteps", DEFAULT_NUM_TIMESTEPS)),
    }


def validate(model_dir: str):
    """验证模型。返回 (ok: bool, errors: list)"""
    model_dir = Path(model_dir).resolve()
    model_py = model_dir / "model.py"
    errors = []

    # ── 0. 检查 model.py 存在 ─────────────────────────────────
    if not model_py.exists():
        msg = f"找不到 model.py: {model_py}"
        print(f"❌ {msg}")
        return False, [msg]

    # ── 1. 加载模型元信息 ─────────────────────────────────────
    meta = load_model_meta(model_dir)
    model_type = meta.get("model_type", "TimeSeries")
    num_features = int(meta.get("num_features", os.environ.get("num_features", DEFAULT_NUM_FEATURES)))
    num_timesteps = int(meta.get("num_timesteps", os.environ.get("num_timesteps", DEFAULT_NUM_TIMESTEPS)))
    print(f"   模型类型: {model_type}")
    print(f"   特征数: {num_features}, 时间步: {num_timesteps}")

    # ── 2. 导入 model_cls ─────────────────────────────────────
    print("🔄 导入 model.py ...")
    try:
        # 动态导入 model.py（参考 RD-Agent 的 from model import model_cls）
        sys.path.insert(0, str(model_dir))
        spec = importlib.util.spec_from_file_location("model", str(model_py))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "model_cls"):
            msg = "model.py 中未定义 model_cls 变量（需要: model_cls = YourModelClass）"
            print(f"❌ {msg}")
            return False, [msg]

        model_cls = module.model_cls
        print(f"   ✅ model_cls = {model_cls.__name__}")
    except Exception as e:
        msg = f"导入 model.py 失败: {type(e).__name__}: {e}"
        print(f"❌ {msg}")
        return False, [msg]
    finally:
        if str(model_dir) in sys.path:
            sys.path.remove(str(model_dir))

    # ── 3. 检查是否为 nn.Module 子类 ─────────────────────────
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        msg = "PyTorch 未安装，无法验证模型"
        print(f"❌ {msg}")
        return False, [msg]

    if not (isinstance(model_cls, type) and issubclass(model_cls, nn.Module)):
        msg = f"model_cls ({model_cls}) 不是 torch.nn.Module 的子类"
        print(f"❌ {msg}")
        return False, [msg]

    # ── 4. 实例化模型（参考 model_execute_template_v1.txt）────
    print("🔄 实例化模型 ...")
    try:
        if model_type == "Tabular":
            m = model_cls(num_features=num_features)
        elif model_type == "TimeSeries":
            m = model_cls(num_features=num_features, num_timesteps=num_timesteps)
        else:
            msg = f"不支持的模型类型: {model_type}（仅支持 Tabular/TimeSeries）"
            print(f"❌ {msg}")
            return False, [msg]
        print(f"   ✅ 实例化成功")
    except Exception as e:
        msg = f"模型实例化失败: {type(e).__name__}: {e}"
        print(f"❌ {msg}")
        return False, [msg]

    # ── 5. 参数数量检查 ───────────────────────────────────────
    total_params = sum(p.numel() for p in m.parameters())
    trainable_params = sum(p.numel() for p in m.parameters() if p.requires_grad)
    print(f"   参数量: {total_params:,} (可训练: {trainable_params:,})")
    if total_params > 100_000_000:
        print(f"   ⚠️ 参数量超过 1 亿，可能导致训练过慢或过拟合")
    if total_params == 0:
        errors.append("模型无可训练参数")

    # ── 6. 初始化参数 + Forward Pass ──────────────────────────
    print("🔄 执行 forward pass ...")
    try:
        # 参考 RD-Agent: 初始化所有参数为固定值
        for _, param in m.named_parameters():
            param.data.fill_(PARAM_INIT_VALUE)

        # 构造 dummy input（参考 model_execute_template_v1.txt）
        if model_type == "Tabular":
            input_shape = (BATCH_SIZE, num_features)
            data = torch.full(input_shape, INPUT_VALUE)
        elif model_type == "TimeSeries":
            input_shape = (BATCH_SIZE, num_timesteps, num_features)
            data = torch.full(input_shape, INPUT_VALUE)

        start_time = time.time()
        m.eval()
        with torch.no_grad():
            out = m(data)
        elapsed = time.time() - start_time

        print(f"   ✅ Forward pass 成功 ({elapsed:.2f}秒)")
        print(f"   输入 shape: {list(data.shape)}")
        print(f"   输出 shape: {list(out.shape)}")
    except Exception as e:
        msg = f"Forward pass 失败: {type(e).__name__}: {e}"
        print(f"❌ {msg}")
        return False, [msg]

    # ── 7. 检查输出 shape ─────────────────────────────────────
    output_arr = out.cpu().detach().numpy()
    expected_shape_1 = (BATCH_SIZE, 1)
    expected_shape_2 = (BATCH_SIZE,)
    if output_arr.shape != expected_shape_1 and output_arr.shape != expected_shape_2:
        errors.append(
            f"输出 shape 不正确: {output_arr.shape}，"
            f"期望 {expected_shape_1} 或 {expected_shape_2}"
        )

    # ── 8. 检查 NaN/Inf ──────────────────────────────────────
    import numpy as np
    nan_count = np.isnan(output_arr).sum()
    inf_count = np.isinf(output_arr).sum()
    if nan_count > 0:
        errors.append(f"输出包含 {nan_count} 个 NaN 值")
    if inf_count > 0:
        errors.append(f"输出包含 {inf_count} 个 Inf 值")

    # ── 9. 检查输出方差（全零 = 无区分度）─────────────────────
    out_flat = output_arr.flatten()
    if len(out_flat) > 1:
        std_val = np.std(out_flat)
        if std_val < 1e-10:
            print(f"   ⚠️ 输出方差近 0 (std={std_val:.2e})，模型可能未正确初始化")
        else:
            print(f"   输出统计: mean={np.mean(out_flat):.4f}, std={std_val:.4f}")

    # ── 汇总 ────────────────────────────────────────────────
    if errors:
        print(f"\n❌ 验证失败 ({len(errors)} 个问题):")
        for i, err in enumerate(errors, 1):
            print(f"   {i}. {err}")
        return False, errors
    else:
        print(f"\n✅ 模型验证通过!")
        print(f"   模型: {model_cls.__name__}")
        print(f"   类型: {model_type}")
        print(f"   参数量: {total_params:,}")
        print(f"   输出 shape: {list(out.shape)}")
        return True, []


def _auto_record_error(model_dir: Path, errors: list):
    """失败时自动调用 collect_error.py 记录错误到知识库"""
    exp_root = model_dir.parent.parent
    collect_py = exp_root / "collect_error.py"
    if not collect_py.exists():
        return
    round_num = 0
    m = re.search(r"round[_\-]?(\d+)", model_dir.parent.name, re.IGNORECASE)
    if m:
        round_num = int(m.group(1))
    error_summary = "; ".join(errors[:3])
    try:
        import subprocess
        subprocess.run(
            [
                sys.executable, str(collect_py), "record",
                "--exp-root", str(exp_root),
                "--round", str(round_num),
                "--stage", "validate_model",
                "--factor", model_dir.name,
                "--error", error_summary,
            ],
            check=False, capture_output=True,
        )
    except Exception:
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python validate_model.py <model_dir>")
        print("  model_dir 需包含 model.py（必须导出 model_cls）")
        sys.exit(1)

    ok, errors = validate(sys.argv[1])
    if not ok and errors:
        _auto_record_error(Path(sys.argv[1]).resolve(), errors)
    sys.exit(0 if ok else 1)
