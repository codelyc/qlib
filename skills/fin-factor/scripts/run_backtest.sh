#!/bin/bash
# 一键回测脚本 — 在 Docker 中执行 Qlib 回测并提取结果
# 借鉴: rdagent/scenarios/qlib/experiment/workspace.py (execute + retry)
#
# 用法:
#   bash run_backtest.sh <round_dir> [config_name]
#
# 参数:
#   round_dir   - 本轮工作目录（需包含 combined_factors_df.parquet + 配置文件）
#   config_name - Qlib 配置文件名 (默认 conf_combined_factors.yaml)
#
# 产出:
#   $round_dir/qlib_res.csv  — 回测指标
#   $round_dir/ret.pkl       — 收益曲线
#   $round_dir/mlruns/       — MLflow 实验记录

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_backtest.sh <round_dir> [config_name]}"
CONFIG_NAME="${2:-conf_combined_factors.yaml}"
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"

# 定位项目根目录（从 ROUND_DIR 回溯: PROJECT_ROOT/factor_workspace/xxx/round_N）
PROJECT_ROOT="$(cd "$ROUND_DIR/../.." && pwd)"
if [ ! -d "$PROJECT_ROOT/data/qlib" ] && [ ! -d "$PROJECT_ROOT/.github" ]; then
    PROJECT_ROOT="$(git -C "$ROUND_DIR" rev-parse --show-toplevel 2>/dev/null || echo "$(cd "$ROUND_DIR/../.." && pwd)")"
fi

IMAGE="local_qlib:latest"
MOUNT_PATH="/workspace/qlib_workspace/"
SHM_SIZE="16g"
MAX_RETRIES=3
RETRY_WAIT=10

# ── 检查前置文件 ────────────────────────────────────────────
echo "🔍 检查文件..."
missing=0
for f in "$CONFIG_NAME" "read_exp_res.py"; do
    if [ ! -f "$ROUND_DIR/$f" ]; then
        echo "  ❌ 缺失: $ROUND_DIR/$f"
        missing=1
    fi
done

if [ "$CONFIG_NAME" = "conf_combined_factors.yaml" ] && [ ! -f "$ROUND_DIR/combined_factors_df.parquet" ]; then
    echo "  ❌ 缺失: $ROUND_DIR/combined_factors_df.parquet"
    missing=1
fi

if [ "$missing" -eq 1 ]; then
    echo "❌ 前置文件检查失败"
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

# ── Docker 回测（带重试）─────────────────────────────────────
run_docker() {
    local entry="$1"
    local attempt=1

    while [ "$attempt" -le "$MAX_RETRIES" ]; do
        echo "  🐳 Docker 执行 (attempt $attempt/$MAX_RETRIES): $entry"

        if docker run --rm \
            -v "$ROUND_DIR":"$MOUNT_PATH" \
            -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
            --shm-size="$SHM_SIZE" \
            "$IMAGE" \
            bash -c "cd $MOUNT_PATH && $entry" 2>&1; then
            return 0
        fi

        echo "  ⚠️ 执行失败，${RETRY_WAIT}秒后重试..."
        sleep "$RETRY_WAIT"
        attempt=$((attempt + 1))
    done

    echo "  ❌ 重试 $MAX_RETRIES 次后仍然失败"
    return 1
}

# ── 运行 qrun 回测 + 提取结果（同一个 Docker 容器）──────────
echo ""
echo "📊 运行 Qlib 回测 + 提取结果 ($CONFIG_NAME)..."
if ! run_docker "qrun $CONFIG_NAME && python read_exp_res.py"; then
    echo "❌ Qlib 回测失败"
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
