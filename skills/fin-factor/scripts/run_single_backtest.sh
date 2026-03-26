#!/bin/bash
# 单因子独立回测脚本 — 在 Docker 中对单个因子做独立回测（当前 ACTIVE_FEATURE_SET + 单因子）
#
# 用法:
#   bash run_single_backtest.sh <round_dir> <factor_name>
#
# 参数:
#   round_dir    - 本轮工作目录
#   factor_name  - 因子子目录名（需已包含 single_factor_df.parquet）
#
# 前置条件:
#   1. 因子已执行生成 result.h5
#   2. merge_factors.py --single <factor_name> 已执行，生成 single_factor_df.parquet
#
# 产出:
#   $round_dir/$factor_name/qlib_res.csv   — 单因子回测指标
#   $round_dir/$factor_name/ret.pkl        — 收益曲线
#   $round_dir/$factor_name/docker_run.log — Docker 执行日志

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_single_backtest.sh <round_dir> <factor_name>}"
FACTOR_NAME="${2:?用法: bash run_single_backtest.sh <round_dir> <factor_name>}"
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"
FACTOR_DIR="$ROUND_DIR/$FACTOR_NAME"
CONFIG_NAME="conf_single_factor.yaml"

# ── 加载公共配置（自动定位 .env 并 source）────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

IMAGE="${DOCKER_IMAGE:-local_qlib:latest}"
MOUNT_PATH="/workspace/qlib_workspace/"
SHM_SIZE="${DOCKER_SHM_SIZE:-16g}"
MAX_RETRIES=3
RETRY_BASE_WAIT=10

echo ""
echo "═══════════════════════════════════════════════════════"
echo "📊 单因子独立回测: $FACTOR_NAME"
echo "═══════════════════════════════════════════════════════"
echo "   因子目录: $FACTOR_DIR"

# ── 检查前置文件 ────────────────────────────────────────────
echo "🔍 检查文件..."
missing=0

if [ ! -d "$FACTOR_DIR" ]; then
    echo "  ❌ 因子目录不存在: $FACTOR_DIR"
    exit 1
fi

if [ ! -f "$FACTOR_DIR/single_factor_df.parquet" ]; then
    echo "  ❌ 缺失: $FACTOR_DIR/single_factor_df.parquet"
    echo "     请先运行: python merge_factors.py $ROUND_DIR --single $FACTOR_NAME"
    missing=1
fi

# 复制所需配置到因子目录（如果不存在）
EXP_ROOT="$(cd "$ROUND_DIR/.." && pwd)"
for f in "$CONFIG_NAME" "read_exp_res.py"; do
    if [ ! -f "$FACTOR_DIR/$f" ]; then
        # 依次从 EXP_ROOT、ROUND_DIR 查找
        if [ -f "$EXP_ROOT/$f" ]; then
            cp "$EXP_ROOT/$f" "$FACTOR_DIR/"
        elif [ -f "$ROUND_DIR/$f" ]; then
            cp "$ROUND_DIR/$f" "$FACTOR_DIR/"
        else
            echo "  ❌ 缺失: $f（在 $EXP_ROOT 和 $ROUND_DIR 中均未找到）"
            missing=1
        fi
    fi
done

if [ "$missing" -eq 1 ]; then
    echo "❌ 前置文件检查失败"
    exit 1
fi

if [ -z "${feature_names:-}" ] || [ -z "${feature_expressions:-}" ]; then
    echo "❌ 缺失特征环境变量 (feature_names, feature_expressions)"
    exit 1
fi

echo "  ✅ 文件检查通过"

# ── 清理旧回测产出（用 Docker root 权限删除）─────────────────
has_old=0
for d in "$FACTOR_DIR/mlruns" "$FACTOR_DIR/workspace"; do
    [ -d "$d" ] && has_old=1
done
if [ "$has_old" -eq 1 ]; then
    echo "🧹 清理旧产出..."
    docker run --rm \
        -v "$FACTOR_DIR":"$MOUNT_PATH" \
        "$IMAGE" \
        bash -c "rm -rf ${MOUNT_PATH}mlruns ${MOUNT_PATH}workspace" 2>/dev/null || true
    echo "  ✅ 清理完成"
fi

# ── Docker 回测（带重试 + 指数退避）──────────────────────────
run_docker() {
    local entry="$1"
    local attempt=1
    local LOG_FILE="$FACTOR_DIR/docker_run.log"

    local env_args=()
    local _qrun_vars=(
        QLIB_PROVIDER_URI market benchmark
        train_start train_end valid_start valid_end test_start test_end
        fit_start_time fit_end_time
        learning_rate max_depth num_leaves num_threads
        colsample_bytree subsample lambda_l1 lambda_l2
        topk n_drop account open_cost close_cost
        MLFLOW_TRACKING_URI
        feature_names feature_expressions
    )
    for _v in "${_qrun_vars[@]}"; do
        [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
    done
    env_args+=(-e "QLIB_PROVIDER_URI=/qlib_data")
    # 固定到当前因子目录，避免读取其他实验的 recorder
    env_args+=(-e "MLFLOW_TRACKING_URI=file://${MOUNT_PATH}mlruns")

    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        echo "  🐳 Docker 执行 (attempt $attempt/$MAX_RETRIES): $entry"

        if docker run --rm \
            -v "$FACTOR_DIR":"$MOUNT_PATH" \
            -v "$QLIB_DATA_DIR":/qlib_data \
            "${env_args[@]}" \
            --shm-size="$SHM_SIZE" \
            ${DOCKER_CPUS:+--cpus="$DOCKER_CPUS"} \
            ${DOCKER_MEMORY:+--memory="$DOCKER_MEMORY"} \
            "$IMAGE" \
            bash -c "cd $MOUNT_PATH && $entry" 2>&1 | tee "$LOG_FILE"; then
            return 0
        fi

        local wait_sec=$(( RETRY_BASE_WAIT * (1 << (attempt - 1)) ))
        echo "  ⚠️ 失败，${wait_sec}秒后重试..."
        sleep "$wait_sec"
        attempt=$((attempt + 1))
    done

    echo "  ❌ 重试 $MAX_RETRIES 次后仍然失败"
    return 1
}

# ── 运行 qrun 回测 ──────────────────────────────────────────
echo ""
echo "📊 运行单因子回测 ($CONFIG_NAME)..."
if ! run_docker "qrun $CONFIG_NAME && python read_exp_res.py"; then
    echo "❌ 单因子回测失败: $FACTOR_NAME"
    echo "  💡 查看日志: $FACTOR_DIR/docker_run.log"
    exit 1
fi
echo "  ✅ 单因子回测完成"

# ── 检查产出 ────────────────────────────────────────────────
echo ""
echo "🔍 检查产出..."
if [ -f "$FACTOR_DIR/qlib_res.csv" ]; then
    echo "  ✅ qlib_res.csv"
    head -10 "$FACTOR_DIR/qlib_res.csv" | sed 's/^/    /'
else
    echo "  ❌ qlib_res.csv 未生成"
    exit 1
fi

echo ""
echo "🎉 单因子回测完成: $FACTOR_NAME → $FACTOR_DIR/qlib_res.csv"
