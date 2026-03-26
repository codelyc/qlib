#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# 一键编排脚本 — 单因子独立回测 → 合并 → 合并回测 → 分析
# ═══════════════════════════════════════════════════════════════
#
# 用法:
#   bash run_round.sh <round_dir>
#
# 流程:
#   阶段 1: 对每个因子做独立回测（当前 ACTIVE_FEATURE_SET + 单因子）
#     1a. merge_factors.py --single <factor>  → single_factor_df.parquet
#     1b. run_single_backtest.sh              → qlib_res.csv (因子目录)
#     1c. analyze_results.py --factor-dir     → analysis.json (因子目录)
#
#   阶段 2: 合并所有因子做联合回测（与原有流程一致）
#     2a. merge_factors.py                    → combined_factors_df.parquet
#     2b. run_backtest.sh                     → qlib_res.csv (round_dir)
#     2c. analyze_results.py                  → analysis.json (含 single_factor_results)
#
# 产出:
#   $round_dir/<factor>/qlib_res.csv     — 每个因子的独立回测指标
#   $round_dir/<factor>/analysis.json    — 每个因子的独立分析
#   $round_dir/qlib_res.csv              — 合并回测指标
#   $round_dir/analysis.json             — 合并分析（含单因子汇总表）
#
# 注意:
#   - 单因子回测仅作参考，不做筛选 — 所有因子都参与最终合并
#   - 每个因子的独立回测约需 5-10 分钟

set -euo pipefail

ROUND_DIR="${1:?用法: bash run_round.sh <round_dir>}"
ROUND_DIR="$(cd "$ROUND_DIR" && pwd)"

# ── 加载公共配置 ─────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

EXP_ROOT="$(cd "$ROUND_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "═══════════════════════════════════════════════════════════"
echo "🚀 一键编排: 单因子独立回测 + 合并回测"
echo "═══════════════════════════════════════════════════════════"
echo "   Round 目录: $ROUND_DIR"
echo "   EXP_ROOT:   $EXP_ROOT"
echo ""

# ── 扫描因子子目录 ───────────────────────────────────────────
FACTORS=()
for sub_dir in "$ROUND_DIR"/*/; do
    [ ! -d "$sub_dir" ] && continue
    factor_name="$(basename "$sub_dir")"
    # 跳过非因子目录（mlruns, workspace 等）
    case "$factor_name" in
        mlruns|workspace|__pycache__) continue ;;
    esac
    # 必须有 result.h5
    if [ -f "$sub_dir/result.h5" ]; then
        FACTORS+=("$factor_name")
    fi
done

if [ "${#FACTORS[@]}" -eq 0 ]; then
    echo "❌ 没有找到因子子目录（需含 result.h5）"
    echo "   请先执行 Docker 全量计算生成 result.h5"
    exit 1
fi

echo "📋 发现 ${#FACTORS[@]} 个因子: ${FACTORS[*]}"
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 1: 单因子独立回测
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 1: 单因子独立回测                                ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

SINGLE_SUCCESS=0
SINGLE_FAIL=0

for factor in "${FACTORS[@]}"; do
    echo "───────────────────────────────────────────────────────"
    echo "📊 [$((SINGLE_SUCCESS + SINGLE_FAIL + 1))/${#FACTORS[@]}] 因子: $factor"
    echo "───────────────────────────────────────────────────────"

    # 1a. 生成单因子 parquet
    echo "  [1/3] merge --single $factor ..."
    if ! "$PYTHON_BIN" "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
        --single "$factor" \
        --sota-file "$EXP_ROOT/sota_combined.parquet" 2>&1; then
        echo "  ⚠️ merge --single 失败，跳过 $factor"
        SINGLE_FAIL=$((SINGLE_FAIL + 1))
        continue
    fi

    # 1b. 单因子回测
    echo "  [2/3] 单因子回测 ..."
    if ! bash "$SCRIPT_DIR/run_single_backtest.sh" "$ROUND_DIR" "$factor" 2>&1; then
        echo "  ⚠️ 单因子回测失败: $factor"
        SINGLE_FAIL=$((SINGLE_FAIL + 1))
        continue
    fi

    # 1c. 分析单因子结果
    echo "  [3/3] 分析结果 ..."
    "$PYTHON_BIN" "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
        --factor-dir "$factor" \
        --sota-file "$EXP_ROOT/sota_record.json" \
        --baseline-file "$EXP_ROOT/baseline_record.json" 2>&1 || true

    SINGLE_SUCCESS=$((SINGLE_SUCCESS + 1))
    echo "  ✅ $factor 独立回测完成"
    echo ""
done

echo ""
echo "📋 单因子回测汇总: ${SINGLE_SUCCESS} 成功, ${SINGLE_FAIL} 失败 / ${#FACTORS[@]} 总计"
echo ""

# ═══════════════════════════════════════════════════════════════
# 阶段 2: 合并回测
# ═══════════════════════════════════════════════════════════════
echo "╔═══════════════════════════════════════════════════════╗"
echo "║  阶段 2: 合并回测                                      ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# 2a. 合并所有因子
echo "[1/3] 合并所有因子..."
if ! "$PYTHON_BIN" "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
    --sota-file "$EXP_ROOT/sota_combined.parquet" 2>&1; then
    echo "❌ 因子合并失败"
    exit 1
fi

# 2b. 合并回测
echo ""
echo "[2/3] 合并回测..."
cp "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/" 2>/dev/null || true
if ! bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR" 2>&1; then
    echo "❌ 合并回测失败"
    exit 1
fi

# 2c. 分析合并结果（自动汇总单因子结果）
echo ""
echo "[3/3] 分析合并结果..."
"$PYTHON_BIN" "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
    --sota-file "$EXP_ROOT/sota_record.json" \
    --baseline-file "$EXP_ROOT/baseline_record.json" 2>&1

# ═══════════════════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "🎉 整轮回测完成!"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "📊 产出文件:"
echo "   单因子结果:"
for factor in "${FACTORS[@]}"; do
    if [ -f "$ROUND_DIR/$factor/qlib_res.csv" ]; then
        echo "     ✅ $factor/analysis.json"
    else
        echo "     ❌ $factor (回测失败)"
    fi
done
echo ""
echo "   合并结果:"
echo "     📄 $ROUND_DIR/analysis.json"
echo "     📈 $ROUND_DIR/qlib_res.csv"
echo ""

# 展示合并分析的简要结论
if [ -f "$ROUND_DIR/analysis.json" ]; then
    echo "📋 合并回测结论:"
    "$PYTHON_BIN" -c "
import json
with open('$ROUND_DIR/analysis.json') as f:
    r = json.load(f)
print(f'   综合评分: {r.get(\"composite_score\", 0):+.4f}')
print(f'   更新SOTA: {\"✅ 是\" if r.get(\"update_sota\") else \"❌ 否\"}')
print(f'   决策说明: {r.get(\"decision_reason\", \"N/A\")}')
sr = r.get('single_factor_results', [])
if sr:
    print(f'   单因子汇总: {len(sr)} 个因子')
    for s in sr:
        ar = s.get('annualized_return')
        ic = s.get('IC')
        ar_s = f'{ar:.4f}' if ar is not None else 'N/A'
        ic_s = f'{ic:.4f}' if ic is not None else 'N/A'
        print(f'     - {s[\"factor\"]}: IC={ic_s}, 年化={ar_s}')
" 2>/dev/null || true
fi

echo ""
echo "下一步: 运行 update_sota.py 更新 SOTA 记录（如果需要）"
