#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 模型回测脚本 — 在 Docker 中执行 Qlib PyTorch 模型回测并提取结果
# ═══════════════════════════════════════════════════════════════
# 来源: fin-factor run_backtest.sh + RD-Agent model_runner.py
#
# 用法:
#   bash run_backtest.sh <round_dir>
#
# 参数:
#   round_dir  - 本轮工作目录（需包含 model.py + conf_*.yaml）
#
# 产出:
#   $round_dir/qlib_res.csv  — 回测指标
#   $round_dir/ret.pkl       — 收益曲线
#   $round_dir/mlruns/       — MLflow 实验记录
#
# 环境变量透传（对齐 RD-Agent model_runner.py env_to_use）:
#   PYTHONPATH, train_start/end, valid_start/end, test_start/end,
#   feature_names, feature_expressions, n_epochs, lr, early_stop,
#   batch_size, weight_decay, dataset_cls, step_len, num_timesteps,
#   num_features, QLIB_PROVIDER_URI

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_backtest.sh <round_dir>}"
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"

# ── 加载公共配置 ─────────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
echo "   项目根: $PROJECT_ROOT"

IMAGE="${DOCKER_IMAGE:-local_qlib:latest}"
MOUNT_PATH="${DOCKER_MOUNT_PATH:-/workspace/qlib_workspace/}"
SHM_SIZE="${DOCKER_SHM_SIZE:-16g}"
MAX_RETRIES="${DOCKER_MAX_RETRIES:-3}"
RETRY_BASE_WAIT="${DOCKER_RETRY_WAIT:-10}"

# ── 自动选择配置文件 ─────────────────────────────────────────
# 参考 RD-Agent model_runner.py: 如果有 combined_factors_df.parquet 则用 sota 配置
if [ -f "$ROUND_DIR/combined_factors_df.parquet" ]; then
    CONFIG_NAME="conf_sota_model.yaml"
    echo "📊 检测到 SOTA 因子文件 → 使用 conf_sota_model.yaml"
else
    CONFIG_NAME="conf_baseline_model.yaml"
    echo "📊 无 SOTA 因子文件 → 使用 conf_baseline_model.yaml"
fi

# ── 检查前置文件 ─────────────────────────────────────────────
echo "🔍 检查文件..."
missing=0
for f in "$CONFIG_NAME" "read_exp_res.py" "model.py"; do
    if [ ! -f "$ROUND_DIR/$f" ]; then
        echo "  ❌ 缺失: $ROUND_DIR/$f"
        missing=1
    fi
done

if [ "$missing" -eq 1 ]; then
    echo "❌ 前置文件检查失败"
    exit 1
fi

if [ -z "${feature_names:-}" ] || [ -z "${feature_expressions:-}" ]; then
    echo "❌ 缺失特征环境变量 (feature_names, feature_expressions)"
    echo "   请确保 common.sh 中正确加载了 default_features.py"
    exit 1
fi

echo "  ✅ 文件检查通过"

# ── 计算 num_features（基础特征 + SOTA 因子）─────────────────
# 参考 RD-Agent model_runner.py: num_features = len(base_features) + len(combined_factors.columns)
_base_feature_count=$(echo "$feature_names" | "${PYTHON_BIN:-python3}" -c "import json,sys; print(len(json.loads(sys.stdin.read())))" 2>/dev/null || echo "${num_features:-20}")
if [ -f "$ROUND_DIR/combined_factors_df.parquet" ]; then
    _sota_factor_count=$("${PYTHON_BIN:-python3}" -c "
import pandas as pd
df = pd.read_parquet('$ROUND_DIR/combined_factors_df.parquet')
print(len(df.columns))
" 2>/dev/null || echo "0")
    # 安全兜底：如果 python 返回空或非数字
    _sota_factor_count="${_sota_factor_count:-0}"
    [[ "$_sota_factor_count" =~ ^[0-9]+$ ]] || _sota_factor_count=0
    _total_features=$(( _base_feature_count + _sota_factor_count ))
    echo "  特征数: 基础=$_base_feature_count + SOTA因子=$_sota_factor_count = $_total_features"
else
    _total_features="$_base_feature_count"
    echo "  特征数: 基础=$_base_feature_count"
fi
export num_features="$_total_features"

# ── 清理旧回测产出（用 Docker root 权限删除）─────────────────
has_old=0
for d in "$ROUND_DIR/mlruns" "$ROUND_DIR/workspace"; do
    [ -d "$d" ] && has_old=1
done
if [ "$has_old" -eq 1 ]; then
    echo ""
    echo "🧹 清理旧回测产出 (mlruns/, workspace/) ..."
    docker run --rm \
        -v "$ROUND_DIR":"$MOUNT_PATH" \
        "$IMAGE" \
        bash -c "rm -rf ${MOUNT_PATH}mlruns ${MOUNT_PATH}workspace" 2>/dev/null || true
    echo "  ✅ 清理完成"
fi

# ── Docker 回测（带重试 + 指数退避）──────────────────────────
run_docker() {
    local entry="$1"
    local attempt=1
    local LOG_FILE="$ROUND_DIR/docker_run.log"

    # 透传环境变量到 Docker 容器（对齐 RD-Agent model_runner.py env_to_use）
    local env_args=()

    # 基础变量（对齐 RD-Agent model_runner.py）
    env_args+=(-e "PYTHONPATH=./")

    # 回测日期参数
    local _date_vars=(train_start train_end valid_start valid_end test_start test_end)
    for _v in "${_date_vars[@]}"; do
        [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
    done

    # 归一化拟合区间
    [ -n "${fit_start_time:-}" ] && env_args+=(-e "fit_start_time=${fit_start_time}")
    [ -n "${fit_end_time:-}" ] && env_args+=(-e "fit_end_time=${fit_end_time}")

    # 特征变量
    env_args+=(-e "feature_names=${feature_names}")
    env_args+=(-e "feature_expressions=${feature_expressions}")

    # PyTorch 训练超参（对齐 RD-Agent model_runner.py）
    local _pt_vars=(n_epochs lr early_stop batch_size weight_decay)
    for _v in "${_pt_vars[@]}"; do
        [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
    done

    # 数据集配置（对齐 RD-Agent model_runner.py）
    local _ds_vars=(dataset_cls step_len num_timesteps num_features)
    for _v in "${_ds_vars[@]}"; do
        [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
    done

    # 策略参数
    local _strat_vars=(market benchmark topk n_drop account open_cost close_cost)
    for _v in "${_strat_vars[@]}"; do
        [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
    done

    # Docker 内 provider_uri 固定为 /qlib_data
    env_args+=(-e "QLIB_PROVIDER_URI=/qlib_data")

    # GPU 支持（对齐 RD-Agent QTDockerConf.enable_gpu=True）
    # 有 GPU 但没配好 → 报错，不降级到 CPU
    # 无 GPU → 正常 CPU（不报错）
    local gpu_flag=""
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        # 宿主机有 GPU → Docker 必须也能用
        if docker info 2>/dev/null | grep -qi "nvidia"; then
            gpu_flag="--gpus all"
            echo "  🖥️ GPU 可用，启用 GPU 加速"
        else
            echo "  ❌ 宿主机有 GPU 但 Docker GPU 运行时未注册"
            echo "     请先运行: bash $MODEL_SKILL_DIR/scripts/main_setup.sh"
            echo "     或手动: sudo apt-get install -y nvidia-container-toolkit && sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
            return 1
        fi
    fi

    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        echo "  🐳 Docker 执行 (attempt $attempt/$MAX_RETRIES): $entry"
        echo "  📝 日志: $LOG_FILE"

        if docker run --rm \
            -v "$ROUND_DIR":"$MOUNT_PATH" \
            -v "$QLIB_DATA_DIR":/qlib_data \
            "${env_args[@]}" \
            --shm-size="$SHM_SIZE" \
            ${DOCKER_CPUS:+--cpus="$DOCKER_CPUS"} \
            ${DOCKER_MEMORY:+--memory="$DOCKER_MEMORY"} \
            $gpu_flag \
            "$IMAGE" \
            bash -c "cd $MOUNT_PATH && $entry" 2>&1 | tee "$LOG_FILE"; then
            return 0
        fi

        local wait_sec=$(( RETRY_BASE_WAIT * (1 << (attempt - 1)) ))
        echo "  ⚠️ 执行失败，${wait_sec}秒后重试 (attempt $attempt/$MAX_RETRIES)..."
        echo "  💡 查看完整日志: $LOG_FILE"
        sleep "$wait_sec"
        attempt=$((attempt + 1))
    done

    echo "  ❌ 重试 $MAX_RETRIES 次后仍然失败"
    echo "  💡 完整错误日志: $LOG_FILE"
    return 1
}

# ── 自动记录回测错误到知识库 ────────────────────────────────
record_backtest_error() {
    local log_file="$1"
    local exp_root
    exp_root="$(cd "$ROUND_DIR/.." && pwd)"
    local collect_py="$exp_root/collect_error.py"
    [ ! -f "$collect_py" ] && return

    local error_summary
    error_summary=$(grep -E "Error|Exception|FAILED|错误|失败" "$log_file" 2>/dev/null | tail -3 | tr '\n' '; ')
    [ -z "$error_summary" ] && error_summary=$(tail -5 "$log_file" 2>/dev/null | tr '\n' '; ')
    error_summary="${error_summary:0:200}"

    local round_num=0
    if [[ "$ROUND_DIR" =~ round[_-]?([0-9]+) ]]; then
        round_num="${BASH_REMATCH[1]}"
    fi

    "${PYTHON_BIN:-python3}" "$collect_py" record \
        --exp-root "$exp_root" \
        --round "$round_num" \
        --stage "model_backtest" \
        --error "$error_summary" 2>/dev/null || true
}

# ── 运行 qrun 回测 + 提取结果 ────────────────────────────────
echo ""
echo "📊 运行 Qlib 模型回测 + 提取结果 ($CONFIG_NAME)..."
if ! run_docker "qrun $CONFIG_NAME && python read_exp_res.py"; then
    echo "❌ Qlib 模型回测失败"
    record_backtest_error "$ROUND_DIR/docker_run.log"
    echo "  💡 错误已自动记录到知识库"
    exit 1
fi
echo "  ✅ 回测 + 结果提取完成"

# ── 检查产出 ────────────────────────────────────────────────
echo ""
echo "🔍 检查产出文件..."
if [ -f "$ROUND_DIR/qlib_res.csv" ]; then
    echo "  ✅ qlib_res.csv"
    echo "  内容:"
    cat "$ROUND_DIR/qlib_res.csv" | head -20 | sed 's/^/    /'
else
    echo "  ❌ qlib_res.csv 未生成"
    exit 1
fi

if [ -f "$ROUND_DIR/ret.pkl" ]; then
    echo "  ✅ ret.pkl ($(du -h "$ROUND_DIR/ret.pkl" | cut -f1))"
else
    echo "  ⚠️ ret.pkl 未生成（不影响指标）"
fi

echo ""
echo "🎉 模型回测完成! 结果在: $ROUND_DIR/qlib_res.csv"
