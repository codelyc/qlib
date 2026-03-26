#!/bin/bash
# 一键回测脚本 — 在 Docker 中执行 Qlib 回测并提取结果
# 借鉴: rdagent/scenarios/qlib/experiment/workspace.py (execute + retry)
#
# 用法:
#   bash run_backtest.sh <round_dir>
#
# 参数:
#   round_dir   - 本轮工作目录（需包含 combined_factors_df.parquet + conf_combined_factors.yaml）
#
# 产出:
#   $round_dir/qlib_res.csv  — 回测指标
#   $round_dir/ret.pkl       — 收益曲线
#   $round_dir/mlruns/       — MLflow 实验记录
#
# 注意:
#   本脚本只负责合并因子回测（conf_combined_factors.yaml）。
#   基线回测请使用 run_baseline.sh，它有自己独立的流程。

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_backtest.sh <round_dir>}"
CONFIG_NAME="conf_combined_factors.yaml"  # 写死，不接受参数。基线回测请用 run_baseline.sh
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"

# ── 加载公共配置（自动定位 .env 并 source）────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
echo "   项目根: $PROJECT_ROOT"

IMAGE="${DOCKER_IMAGE:-local_qlib:latest}"
MOUNT_PATH="/workspace/qlib_workspace/"
SHM_SIZE="${DOCKER_SHM_SIZE:-16g}"
MAX_RETRIES=3
RETRY_BASE_WAIT=10  # 指数退避基数（秒），实际等待 = BASE * 2^(attempt-1)

# ── 检查前置文件 ────────────────────────────────────────────
echo "🔍 检查文件..."
missing=0
for f in "$CONFIG_NAME" "read_exp_res.py"; do
    if [ ! -f "$ROUND_DIR/$f" ]; then
        echo "  ❌ 缺失: $ROUND_DIR/$f"
        missing=1
    fi
done

if [ ! -f "$ROUND_DIR/combined_factors_df.parquet" ]; then
    echo "  ❌ 缺失: $ROUND_DIR/combined_factors_df.parquet"
    echo "     请先运行 merge_factors.py 合并因子"
    missing=1
fi

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

    # 透传 .env 中的回测参数到 Docker 容器
    # .env 中已使用小写变量名，与 YAML 模板 {{ var }} 一致，qrun 直接读取
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
    # Docker 内 provider_uri 固定为 /qlib_data（覆盖 .env 中的本地路径）
    env_args+=(-e "QLIB_PROVIDER_URI=/qlib_data")
    # 固定到当前 round 目录，避免读取其他实验的 recorder
    env_args+=(-e "MLFLOW_TRACKING_URI=file://${MOUNT_PATH}mlruns")

    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        echo "  🐳 Docker 执行 (attempt $attempt/$MAX_RETRIES): $entry"
        echo "  📝 日志: $LOG_FILE"

        # 日志同时输出到 stdout 和文件（tee），方便事后调试
        if docker run --rm \
            -v "$ROUND_DIR":"$MOUNT_PATH" \
            -v "$QLIB_DATA_DIR":/qlib_data \
            "${env_args[@]}" \
            --shm-size="$SHM_SIZE" \
            ${DOCKER_CPUS:+--cpus="$DOCKER_CPUS"} \
            ${DOCKER_MEMORY:+--memory="$DOCKER_MEMORY"} \
            "$IMAGE" \
            bash -c "cd $MOUNT_PATH && $entry" 2>&1 | tee "$LOG_FILE"; then
            return 0
        fi

        local wait_sec=$(( RETRY_BASE_WAIT * (1 << (attempt - 1)) ))  # 指数退避: 10s, 20s, 40s
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
    # exp_root = ROUND_DIR 的上上级 (exp_root/round_N)
    exp_root="$(cd "$ROUND_DIR/.." && pwd)"
    local collect_py="$exp_root/collect_error.py"
    [ ! -f "$collect_py" ] && return

    # 从日志中提取最后几行关键错误信息
    local error_summary
    error_summary=$(grep -E "Error|Exception|FAILED|错误|失败" "$log_file" 2>/dev/null | tail -3 | tr '\n' '; ')
    [ -z "$error_summary" ] && error_summary=$(tail -5 "$log_file" 2>/dev/null | tr '\n' '; ')
    error_summary="${error_summary:0:200}"  # 截断到200字符

    # 推断轮次号
    local round_num=0
    if [[ "$ROUND_DIR" =~ round[_-]?([0-9]+) ]]; then
        round_num="${BASH_REMATCH[1]}"
    fi

    python3 "$collect_py" record \
        --exp-root "$exp_root" \
        --round "$round_num" \
        --stage "backtest" \
        --error "$error_summary" 2>/dev/null || true
}

# ── 运行 qrun 回测 + 提取结果（同一个 Docker 容器）──────────
echo ""
echo "📊 运行 Qlib 回测 + 提取结果 ($CONFIG_NAME)..."
if ! run_docker "qrun $CONFIG_NAME && python read_exp_res.py"; then
    echo "❌ Qlib 回测失败"
    # 自动记录到错误知识库
    record_backtest_error "$ROUND_DIR/docker_run.log"
    echo "  💡 错误已自动记录到知识库，请用 annotate 命令补充根因"
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
echo "🎉 回测完成! 结果在: $ROUND_DIR/qlib_res.csv"
