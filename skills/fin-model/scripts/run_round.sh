#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 一键编排脚本 — 验证模型 → Docker 回测 → 结果分析
# ═══════════════════════════════════════════════════════════════
# 来源: fin-factor run_round.sh（简化版，无因子合并步骤）
#
# 用法:
#   bash run_round.sh <round_dir>
#
# 流程:
#   1. 扫描模型子目录，找到 model.py
#   2. 验证模型 (validate_model.py)
#   3. 复制模型+配置到 round_dir 顶层
#   4. Docker 回测 (run_backtest.sh)
#   5. 结果分析 (analyze_results.py)
#
# 产出:
#   $round_dir/qlib_res.csv       — 回测指标
#   $round_dir/analysis.json      — 结构化分析报告
#   $round_dir/docker_run.log     — Docker 训练日志

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_round.sh <round_dir>}"
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"

# ── 加载公共配置 ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

EXP_ROOT="$(cd "$ROUND_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "═══════════════════════════════════════════════════════════"
echo "🚀 模型优化一键编排"
echo "═══════════════════════════════════════════════════════════"
echo "   Round 目录: $ROUND_DIR"
echo "   EXP_ROOT:   $EXP_ROOT"
echo ""

# ── 扫描模型子目录 ───────────────────────────────────────────
MODEL_DIR=""
MODEL_NAME=""
for sub_dir in "$ROUND_DIR"/*/; do
    [ ! -d "$sub_dir" ] && continue
    name="$(basename "$sub_dir")"
    case "$name" in
        mlruns|workspace|__pycache__) continue ;;
    esac
    if [ -f "$sub_dir/model.py" ]; then
        MODEL_DIR="$sub_dir"
        MODEL_NAME="$name"
        break
    fi
done

# 也检查 round_dir 顶层
if [ -z "$MODEL_DIR" ] && [ -f "$ROUND_DIR/model.py" ]; then
    MODEL_DIR="$ROUND_DIR"
    MODEL_NAME="$(basename "$ROUND_DIR")"
fi

if [ -z "$MODEL_DIR" ]; then
    echo "❌ 没有找到模型子目录（需含 model.py）"
    echo "   请先编写 model.py 到 $ROUND_DIR/<model_name>/model.py"
    exit 1
fi

echo "📋 模型: $MODEL_NAME ($MODEL_DIR)"
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 1: 快速验证
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 1: 快速验证 (forward pass)                      ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

if ! "$PYTHON_BIN" "$EXP_ROOT/validate_model.py" "$MODEL_DIR" 2>&1; then
    echo ""
    echo "❌ 模型验证失败，请修复 model.py 后重试"
    exit 1
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 2: 准备回测文件
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 2: 准备回测文件                                  ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# 复制 model.py 到 round_dir 顶层（Qlib qrun 在工作目录执行）
if [ "$MODEL_DIR" != "$ROUND_DIR" ]; then
    cp "$MODEL_DIR/model.py" "$ROUND_DIR/model.py"
    echo "  ✅ model.py → $ROUND_DIR/"
fi

# 复制 model_meta.json（如果有）
if [ -f "$MODEL_DIR/model_meta.json" ]; then
    cp "$MODEL_DIR/model_meta.json" "$ROUND_DIR/model_meta.json"
fi

# 确保配置文件存在
for f in conf_baseline_model.yaml conf_sota_model.yaml read_exp_res.py; do
    if [ ! -f "$ROUND_DIR/$f" ] && [ -f "$EXP_ROOT/$f" ]; then
        cp "$EXP_ROOT/$f" "$ROUND_DIR/$f"
    fi
done

# 如果有 SOTA 因子，复制
if [ -f "$EXP_ROOT/combined_factors_df.parquet" ] && [ ! -f "$ROUND_DIR/combined_factors_df.parquet" ]; then
    cp "$EXP_ROOT/combined_factors_df.parquet" "$ROUND_DIR/"
    echo "  ✅ SOTA 因子文件已复制"
fi

echo "  ✅ 回测文件准备完成"
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 3: Docker 回测
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 3: Docker 回测                                   ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

if ! bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR" 2>&1; then
    echo ""
    echo "❌ Docker 回测失败"
    exit 1
fi
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 4: 结果分析
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 4: 结果分析                                      ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

"$PYTHON_BIN" "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
    --sota-file "$EXP_ROOT/sota_record.json" 2>&1

# ═══════════════════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🎉 模型回测完成!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📊 产出文件:"
echo "     📄 $ROUND_DIR/analysis.json"
echo "     📈 $ROUND_DIR/qlib_res.csv"
echo "     📝 $ROUND_DIR/docker_run.log"
echo ""

# 展示分析结论
if [ -f "$ROUND_DIR/analysis.json" ]; then
    echo "📋 回测结论:"
    "$PYTHON_BIN" -c "
import json
with open('$ROUND_DIR/analysis.json') as f:
    r = json.load(f)
print(f'   综合评分: {r.get(\"composite_score\", 0):+.4f}')
print(f'   更新SOTA: {\"✅ 是\" if r.get(\"update_sota\") else \"❌ 否\"}')
print(f'   决策说明: {r.get(\"decision_reason\", \"N/A\")}')
" 2>/dev/null || true
fi

echo ""
echo "下一步: 运行 update_sota.py 更新 SOTA 记录（如果需要）"
