#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 静态基线回测脚本 — 跑一次当前 ACTIVE_FEATURE_SET 基线，保存到 baseline_record.json
#
# 用法:
#   bash run_baseline.sh [exp_root]
#   bash run_baseline.sh [exp_root] --force   # 覆盖已有基线
#
# 产出:
#   $EXP_ROOT/baseline_record.json — 静态基线指标（后续不变）
#
# 说明:
#   init_workspace.sh 末尾自动调用此脚本。后续轮次不再执行。
#   如果 baseline_record.json 已存在，默认跳过（传 --force 可覆盖）。
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── 参数解析 ─────────────────────────────────────────────────
FORCE=0; POSITIONAL=()
for arg in "$@"; do
    case $arg in --force) FORCE=1 ;; *) POSITIONAL+=("$arg") ;; esac
done
EXP_ROOT_ARG="${POSITIONAL[0]:-}"

# ── 加载公共配置 ─────────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
IMAGE="${DOCKER_IMAGE:-local_qlib:latest}"

if [ -n "$EXP_ROOT_ARG" ]; then
    EXP_ROOT="$(cd "$EXP_ROOT_ARG" && pwd)"
fi

if [ -z "${EXP_ROOT:-}" ]; then
    echo "❌ EXP_ROOT 未设置。请在 .env 中设置 EXP_ROOT，或传入参数:"
    echo "   bash run_baseline.sh <exp_root>"
    exit 1
fi

BASELINE_FILE="$EXP_ROOT/baseline_record.json"
BASELINE_DIR="$EXP_ROOT/_baseline_run"

# ── 幂等检查 ─────────────────────────────────────────────────
if [ -f "$BASELINE_FILE" ] && [ "$FORCE" -eq 0 ]; then
    echo "ℹ️  baseline_record.json 已存在，跳过基线回测"
    echo "   (传 --force 可覆盖重跑)"
    exit 0
fi

echo "📊 运行静态基线回测（${ACTIVE_FEATURE_SET:-ALPHA20} + 默认 LightGBM，无新因子）..."

# ── 准备临时目录（用 Docker 清理 root 文件）─────────────────
if [ -d "$BASELINE_DIR" ]; then
    docker run --rm -v "$BASELINE_DIR":/cleanup "$IMAGE" \
        bash -c "rm -rf /cleanup/*" 2>/dev/null || true
    rm -rf "$BASELINE_DIR" 2>/dev/null || true
fi
mkdir -p "$BASELINE_DIR"
cp "$EXP_ROOT/conf_baseline.yaml" "$BASELINE_DIR/"
cp "$EXP_ROOT/read_exp_res.py" "$BASELINE_DIR/"

# ── Docker 回测 ──────────────────────────────────────────────
SHM_SIZE="${DOCKER_SHM_SIZE:-16g}"
MOUNT_PATH="/workspace/qlib_workspace/"
LOG_FILE="$BASELINE_DIR/docker_run.log"

# 透传回测参数到 Docker
env_args=()
for _v in QLIB_PROVIDER_URI market benchmark \
    train_start train_end valid_start valid_end test_start test_end \
    fit_start_time fit_end_time \
    learning_rate max_depth num_leaves num_threads \
    colsample_bytree subsample lambda_l1 lambda_l2 \
    topk n_drop account open_cost close_cost \
    MLFLOW_TRACKING_URI feature_names feature_expressions; do
    [ -n "${!_v:-}" ] && env_args+=(-e "$_v=${!_v}")
done
# Docker 内 provider_uri 固定为 /qlib_data
env_args+=(-e "QLIB_PROVIDER_URI=/qlib_data")
# 固定到 baseline 目录，避免读取其他实验的 recorder
env_args+=(-e "MLFLOW_TRACKING_URI=file://${MOUNT_PATH}mlruns")

echo "  🐳 Docker 基线回测中..."
# 注意：用 set +o pipefail 避免 tee 的 SIGPIPE 导致误判 Docker 退出码
set +o pipefail
docker run --rm \
    -v "$BASELINE_DIR":"$MOUNT_PATH" \
    -v "$QLIB_DATA_DIR":/qlib_data \
    "${env_args[@]}" \
    --shm-size="$SHM_SIZE" \
    ${DOCKER_CPUS:+--cpus="$DOCKER_CPUS"} \
    ${DOCKER_MEMORY:+--memory="$DOCKER_MEMORY"} \
    "$IMAGE" \
    bash -c "cd $MOUNT_PATH && qrun conf_baseline.yaml && python read_exp_res.py" 2>&1 | tee "$LOG_FILE"
DOCKER_EXIT=${PIPESTATUS[0]}
set -o pipefail

if [ "$DOCKER_EXIT" -ne 0 ]; then
    echo "  ⚠️ Docker 退出码 $DOCKER_EXIT（可能是警告，检查产出文件）"
fi

# ── 检查产出 ─────────────────────────────────────────────────
QLIB_RES="$BASELINE_DIR/qlib_res.csv"
if [ ! -f "$QLIB_RES" ]; then
    echo "  ❌ qlib_res.csv 未生成"
    exit 1
fi

# ── CSV → baseline_record.json ───────────────────────────────
python3 << PYEOF
import csv, json, datetime
from pathlib import Path

metrics = {}
with open("${BASELINE_DIR}/qlib_res.csv") as f:
    for row in csv.reader(f):
        if len(row) >= 2:
            metrics[row[0].strip()] = float(row[1])

baseline = {
    "type": "baseline",
    "description": "${ACTIVE_FEATURE_SET:-ALPHA20} + default LightGBM, no custom factors",
    "metrics": metrics,
    "generated_at": datetime.datetime.now().isoformat()
}

out = Path("${BASELINE_FILE}")
with open(out, "w") as f:
    json.dump(baseline, f, indent=2, ensure_ascii=False)

print(json.dumps(baseline, indent=2, ensure_ascii=False))
PYEOF

echo ""
echo "✅ 静态基线已保存: $BASELINE_FILE"
echo "   此文件后续不会被覆盖（除非传 --force 重跑）"
echo "   回测日志: $LOG_FILE"
