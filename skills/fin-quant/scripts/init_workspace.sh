#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 初始化联合优化工作空间（因子 + 模型）
# ═══════════════════════════════════════════════════════════════
# 用法: bash init_workspace.sh [workspace_name]
#
# 产出:
#   $QUANT_EXP_ROOT/ 包含:
#     - 因子基础设施（daily_pv.h5, 因子 YAML 模板）
#     - 模型基础设施（模型 YAML 模板, model_sota/）
#     - 联合设施（quant_trace.json, 统一 sota_record.json）
#     - conf_factor_with_sota_model.yaml（★新增：用 SOTA 模型评估因子）
#
# 注意: 本脚本调用 fin-factor 的 gen_daily_pv.py 生成数据，
#       从 fin-factor/assets 和 fin-model/assets 复制 YAML 模板。
#       不复制脚本 — 运行时通过 $SKILL_DIR/$MODEL_SKILL_DIR 调用。

set -euo pipefail

# ── 0. 加载公共配置 ──────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKSPACE_NAME="${1:-quant_$TIMESTAMP}"
EXP_ROOT="${QUANT_EXP_ROOT:-$PROJECT_ROOT/factor_workspace/$WORKSPACE_NAME}"

echo "🚀 初始化联合优化工作空间（因子 + 模型）"
echo "   项目根: $PROJECT_ROOT"
echo "   路径:   $EXP_ROOT"
echo "   fin-factor: $SKILL_DIR"
echo "   fin-model:  $MODEL_SKILL_DIR"

# ── 1. 创建目录 ──────────────────────────────────────────────
mkdir -p "$EXP_ROOT"
mkdir -p "$EXP_ROOT/model_sota"     # SOTA model.py 备份

# ── 2. 复制 YAML 模板 ───────────────────────────────────────
echo ""
echo "📋 复制 YAML 模板..."

# 因子相关配置（从 fin-factor/assets）
cp "$SKILL_DIR/assets/conf_baseline.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/conf_combined_factors.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/conf_single_factor.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/read_exp_res.py" "$EXP_ROOT/"

# 模型相关配置（从 fin-model/assets）
cp "$MODEL_SKILL_DIR/assets/conf_baseline_model.yaml" "$EXP_ROOT/"
cp "$MODEL_SKILL_DIR/assets/conf_sota_model.yaml" "$EXP_ROOT/"
cp "$MODEL_SKILL_DIR/assets/read_exp_res.py" "$EXP_ROOT/read_exp_res_model.py"

# 联合配置（从 fin-quant/assets — 用 SOTA 模型评估因子，★新增）
cp "$QUANT_SKILL_DIR/assets/conf_factor_with_sota_model.yaml" "$EXP_ROOT/"

echo "  ✅ YAML 模板复制完成"

# ── 3. 复制辅助数据脚本到工作区（仅数据生成相关）──────────────
# gen_daily_pv.py 和 default_features.py 需要在 Docker 内执行
# collect_error.py 需要在工作区内，因为 error_knowledge.jsonl 在工作区
for script in gen_daily_pv.py default_features.py; do
    cp "$SKILL_DIR/scripts/$script" "$EXP_ROOT/"
done

echo "  ✅ 辅助脚本复制完成"

# ── 4. 初始化追踪文件 ───────────────────────────────────────
# 统一 SOTA 记录
cat > "$EXP_ROOT/sota_record.json" << 'EOF'
{
  "round": 0,
  "factor_sota": {
    "factors": [],
    "metrics": null
  },
  "model_sota": {
    "model_name": null,
    "model_type": null,
    "metrics": null,
    "training_hyperparameters": null
  },
  "combined_metrics": null,
  "history": []
}
EOF

# 统一实验追踪（含 Bandit 状态）
cat > "$EXP_ROOT/quant_trace.json" << 'EOF'
{
  "rounds": [],
  "bandit_state": {
    "factor_rewards": [],
    "model_rewards": [],
    "factor_count": 0,
    "model_count": 0
  }
}
EOF

echo "  ✅ 追踪文件初始化完成"

# ── 5. 环境前置校验 ──────────────────────────────────────────
_env_ok=1
if ! docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "${IMAGE}"; then
    echo "❌ Docker 镜像 $IMAGE 不存在"; _env_ok=0
fi
if [ ! -d "$QLIB_DATA_DIR/features" ] || [ ! -d "$QLIB_DATA_DIR/calendars" ]; then
    echo "❌ Qlib 数据不完整: $QLIB_DATA_DIR"; _env_ok=0
fi
if [ "$_env_ok" -eq 0 ]; then
    echo ""
    echo "⚠️  环境未就绪，请先运行环境初始化脚本:"
    echo "   bash $SKILL_DIR/scripts/main_setup.sh"
    echo ""
    exit 1
fi

# ── 6. 生成数据文件 ──────────────────────────────────────────
echo ""
echo "📊 在 Docker 中生成数据文件 (daily_pv.h5 + daily_pv_debug.h5)..."
echo "   这可能需要几分钟..."

docker run --rm \
  -v "$EXP_ROOT":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/qlib/data":/qlib_data \
  --shm-size="$SHM_SIZE" \
  "$IMAGE" \
  bash -c "cd /workspace/qlib_workspace && python gen_daily_pv.py"

# 验证
if [ ! -f "$EXP_ROOT/daily_pv.h5" ] || [ ! -f "$EXP_ROOT/daily_pv_debug.h5" ]; then
    echo "❌ 数据生成失败"
    exit 1
fi

echo "  ✅ daily_pv.h5 ($(du -h "$EXP_ROOT/daily_pv.h5" | cut -f1))"
echo "  ✅ daily_pv_debug.h5 ($(du -h "$EXP_ROOT/daily_pv_debug.h5" | cut -f1))"

# ── 7. 完成 ──────────────────────────────────────────────────
echo ""
echo "🎉 联合优化工作空间初始化完成!"
echo ""
echo "📁 目录结构:"
echo "   $EXP_ROOT/"
echo "   ├── daily_pv.h5                      ← 全量数据 (因子轮次共用)"
echo "   ├── daily_pv_debug.h5                ← 调试数据 (因子快速验证)"
echo "   ├── conf_baseline.yaml               ← 因子基线配置 (LightGBM)"
echo "   ├── conf_combined_factors.yaml       ← 因子合并配置 (LightGBM)"
echo "   ├── conf_single_factor.yaml          ← 单因子配置 (LightGBM)"
echo "   ├── conf_baseline_model.yaml         ← 模型基线配置 (PyTorch)"
echo "   ├── conf_sota_model.yaml             ← 模型+SOTA因子配置 (PyTorch)"
echo "   ├── conf_factor_with_sota_model.yaml ← ★因子+SOTA模型配置 (PyTorch)"
echo "   ├── quant_trace.json                 ← 联合实验追踪 (含 Bandit)"
echo "   ├── sota_record.json                 ← 联合 SOTA 记录"
echo "   └── model_sota/                      ← SOTA model.py 备份"
echo ""
echo "ℹ️  回测参数统一在 .env 中配置"
echo ""
echo "📌 调用关系:"
echo "   因子脚本 → $SKILL_DIR/scripts/"
echo "   模型脚本 → $MODEL_SKILL_DIR/scripts/"
echo "   编排脚本 → $QUANT_SKILL_DIR/scripts/"
echo ""
echo "QUANT_EXP_ROOT=$EXP_ROOT"
