#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 初始化模型优化工作空间
# ═══════════════════════════════════════════════════════════════
# 用法: bash init_workspace.sh [workspace_name]
#
# 产出:
#   $MODEL_EXP_ROOT/ 包含所有需要的模板和脚本
#   注意: 不生成 daily_pv.h5（模型优化不需要因子数据文件，特征由 Qlib Alpha158DL 在 Docker 内计算）

set -euo pipefail

# ── 0. 加载公共配置 ──────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKSPACE_NAME="${1:-model_$TIMESTAMP}"
EXP_ROOT="${MODEL_EXP_ROOT:-$PROJECT_ROOT/factor_workspace/$WORKSPACE_NAME}"

echo "🚀 初始化模型优化工作空间"
echo "   项目根: $PROJECT_ROOT"
echo "   路径: $EXP_ROOT"

# ── 1. 创建目录 ──────────────────────────────────────────────
mkdir -p "$EXP_ROOT"
mkdir -p "$EXP_ROOT/model_sota"  # 存储 SOTA model.py 备份

# ── 2. 复制模板文件 ──────────────────────────────────────────
echo "📋 复制模板文件..."
cp "$MODEL_SKILL_DIR/assets/conf_baseline_model.yaml" "$EXP_ROOT/"
cp "$MODEL_SKILL_DIR/assets/conf_sota_model.yaml" "$EXP_ROOT/"
cp "$MODEL_SKILL_DIR/assets/read_exp_res.py" "$EXP_ROOT/"

# 复制脚本
for script in validate_model.py run_backtest.sh run_round.sh \
              analyze_results.py update_sota.py collect_error.py \
              common.sh default_features.py; do
    if [ -f "$MODEL_SKILL_DIR/scripts/$script" ]; then
        cp "$MODEL_SKILL_DIR/scripts/$script" "$EXP_ROOT/"
    fi
done

# ── 3. 初始化 SOTA 记录 ─────────────────────────────────────
cat > "$EXP_ROOT/sota_record.json" << 'EOF'
{
  "round": 0,
  "model_name": null,
  "model_type": null,
  "sota_metrics": null,
  "training_hyperparameters": null,
  "history": []
}
EOF

echo "  ✅ 文件复制完成"

# ── 4. 环境前置校验（详细检查由 main_setup.sh 负责）─────────
_env_ok=1
if ! docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "${IMAGE}"; then
    echo "❌ Docker 镜像 $IMAGE 不存在"; _env_ok=0
fi
if [ ! -d "$QLIB_DATA_DIR/features" ] || [ ! -d "$QLIB_DATA_DIR/calendars" ]; then
    echo "❌ Qlib 数据不完整: $QLIB_DATA_DIR"; _env_ok=0
fi
if [ "$_env_ok" -eq 0 ]; then
    echo ""
    echo "⚠️  环境未就绪，请先运行入口脚本:"
    echo "   bash $MODEL_SKILL_DIR/scripts/main_setup.sh"
    echo ""
    echo "   该脚本会自动检查并修复 Docker、Qlib 数据、GPU 等所有依赖。"
    exit 1
fi

# ── 5. 检查 SOTA 因子（可选）────────────────────────────────
# 如果用户手动放置了 SOTA 因子文件，自动启用增强特征配置
echo ""
if [ -n "${FACTOR_WORKSPACE_DIR:-}" ]; then
    # 尝试从因子工作区自动发现（需用户在 .env 中设置 FACTOR_WORKSPACE_DIR）
    _found_parquet=""
    for _f in "$FACTOR_WORKSPACE_DIR"/*/sota_combined.parquet; do
        [ -f "$_f" ] && _found_parquet="$_f" && break
    done
    if [ -n "$_found_parquet" ]; then
        cp "$_found_parquet" "$EXP_ROOT/combined_factors_df.parquet"
        echo "📊 已导入 SOTA 因子: $_found_parquet"
        echo "   → 回测将自动使用 conf_sota_model.yaml（Alpha158 + SOTA因子 + 新模型）"
    else
        echo "ℹ️  无 SOTA 因子文件（可选 — 模型将只使用 Alpha20/158 基础特征）"
        echo "   如需加载因子，将 sota_combined.parquet 复制到 $EXP_ROOT/combined_factors_df.parquet"
    fi
else
    echo "ℹ️  无 SOTA 因子文件（可选 — 模型将只使用 Alpha20/158 基础特征）"
    echo "   如需加载因子，将 sota_combined.parquet 复制到 $EXP_ROOT/combined_factors_df.parquet"
fi

# ── 7. 完成 ──────────────────────────────────────────────────
echo ""
echo "🎉 模型优化工作空间初始化完成!"
echo ""
echo "📁 目录结构:"
echo "   $EXP_ROOT/"
echo "   ├── conf_baseline_model.yaml  ← Alpha158 + 新模型 (Jinja2 模板)"
echo "   ├── conf_sota_model.yaml      ← Alpha158 + SOTA因子 + 新模型"
echo "   ├── read_exp_res.py           ← 回测结果提取"
echo "   ├── validate_model.py         ← 模型快速验证 (forward pass)"
echo "   ├── run_backtest.sh           ← Docker 回测"
echo "   ├── run_round.sh             ← 一键编排 (验证→回测→分析)"
echo "   ├── analyze_results.py        ← 结果分析"
echo "   ├── update_sota.py            ← SOTA 更新"
echo "   ├── collect_error.py          ← 错误知识库"
echo "   ├── sota_record.json          ← SOTA 追踪"
echo "   └── model_sota/               ← SOTA model.py 备份"
echo ""
echo "ℹ️  回测参数统一在 .env 中配置，qrun 自动读取环境变量"
echo ""
echo "下一步: 创建 round_1/ 目录并编写 model.py"
echo "   mkdir -p $EXP_ROOT/round_1/<model_name>"
echo ""
echo "MODEL_EXP_ROOT=$EXP_ROOT"
