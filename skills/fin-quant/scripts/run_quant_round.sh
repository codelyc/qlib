#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# run_quant_round.sh — 联合优化统一编排
# ═══════════════════════════════════════════════════════════════
# 根据 action (factor/model) 调用 fin-factor 或 fin-model 的脚本。
#
# 用法:
#   bash run_quant_round.sh <round_dir> <action>
#
# 参数:
#   round_dir  — 当前轮次目录 (如 $QUANT_EXP_ROOT/round_1)
#   action     — "factor" 或 "model"
#
# 流程:
#   1. 准备交叉集成数据 (prepare_cross_data.py)
#   2. 根据 action 路由到对应子 skill 脚本
#   3. 分析结果
#   4. 更新 SOTA + Trace
#
# 注意: 本脚本调用 fin-factor/fin-model 的脚本，不复制。

set -euo pipefail

# ── 参数 ─────────────────────────────────────────────────────
ROUND_DIR="${1:?用法: bash run_quant_round.sh <round_dir> <action>}"
ACTION="${2:?用法: bash run_quant_round.sh <round_dir> <action>}"

if [[ "$ACTION" != "factor" && "$ACTION" != "model" ]]; then
    echo "❌ action 必须是 factor 或 model，收到: $ACTION"
    exit 1
fi

# ── 加载配置 ─────────────────────────────────────────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

# 从路径推断 EXP_ROOT (round_dir 的父目录)
EXP_ROOT="$(dirname "$ROUND_DIR")"

echo "═══════════════════════════════════════════════════════════"
echo "🔄 联合优化 — Round $(basename "$ROUND_DIR") — Action: $ACTION"
echo "═══════════════════════════════════════════════════════════"
echo "   工作区:   $EXP_ROOT"
echo "   轮次目录: $ROUND_DIR"
echo "   fin-factor: $SKILL_DIR"
echo "   fin-model:  $MODEL_SKILL_DIR"
echo ""

# ── 1. 保存 action 信息 ─────────────────────────────────────
mkdir -p "$ROUND_DIR"
cat > "$ROUND_DIR/action.json" << EOF
{
  "action": "$ACTION",
  "timestamp": "$(date -Iseconds)"
}
EOF

# ── 2. 准备交叉集成数据 ─────────────────────────────────────
echo "📦 准备交叉集成数据..."
$PYTHON_BIN "$QUANT_SKILL_DIR/scripts/prepare_cross_data.py" \
    --exp-root "$EXP_ROOT" \
    --round-dir "$ROUND_DIR" \
    --action "$ACTION" \
    --base-features "${num_features:-20}"
echo ""

# ── 3. 路由到子 skill ────────────────────────────────────────
if [ "$ACTION" = "factor" ]; then
    echo "🔬 === 因子回测流程 ==="
    echo ""

    # 调用 fin-factor 的 run_round.sh
    # run_round.sh 期望: bash run_round.sh <round_dir>
    # 它会自动: 扫描因子 → 单因子回测 → 合并 → 合并回测 → 分析
    #
    # 前置条件:
    #   - round_dir 下有 {factor_name}/factor.py (Agent 已写好)
    #   - EXP_ROOT 下有 daily_pv.h5, validate_factor.py 等 (init_workspace 已复制)
    #   - EXP_ROOT 下有 YAML 模板 (init_workspace 已复制)

    # 因子脚本期望在 EXP_ROOT 下找到辅助文件，
    # 但我们的 EXP_ROOT 就是 QUANT_EXP_ROOT (init_workspace 已复制全部)
    bash "$SKILL_DIR/scripts/run_round.sh" "$ROUND_DIR"

elif [ "$ACTION" = "model" ]; then
    echo "🤖 === 模型回测流程 ==="
    echo ""

    # 调用 fin-model 的 run_round.sh
    # 它期望: round_dir 下有 model.py + model_meta.json (Agent 已写好)
    bash "$MODEL_SKILL_DIR/scripts/run_round.sh" "$ROUND_DIR"
fi

ROUND_EXIT=$?

if [ "$ROUND_EXIT" -ne 0 ]; then
    echo ""
    echo "❌ $ACTION 回测失败 (exit code: $ROUND_EXIT)"
    echo "   查看日志: cat $ROUND_DIR/docker_run.log"
    exit $ROUND_EXIT
fi

# ── 4. 更新 SOTA ────────────────────────────────────────────
echo ""
echo "📊 更新统一 SOTA..."
ROUND_NUM=$(basename "$ROUND_DIR" | sed 's/round_//')
$PYTHON_BIN "$QUANT_SKILL_DIR/scripts/update_quant_sota.py" \
    "$EXP_ROOT" "$ROUND_DIR" "$ROUND_NUM" "$ACTION"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ Round $(basename "$ROUND_DIR") ($ACTION) 完成"
echo "═══════════════════════════════════════════════════════════"
