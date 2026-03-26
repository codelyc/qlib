#!/bin/bash
# 初始化因子研发工作空间
# 用法: bash init_workspace.sh [workspace_name]
#
# 产出:
#   $EXP_ROOT/ 包含所有需要的模板和脚本
#   daily_pv.h5 + daily_pv_debug.h5 在 Docker 中生成

set -euo pipefail

# ── 0. 加载公共配置（自动定位 .env 并 source）────────────
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WORKSPACE_NAME="${1:-$TIMESTAMP}"
EXP_ROOT="$PROJECT_ROOT/factor_workspace/$WORKSPACE_NAME"

echo "🚀 初始化因子研发工作空间"
echo "   项目根: $PROJECT_ROOT"
echo "   路径: $EXP_ROOT"

# ── 1. 创建目录 ──────────────────────────────────────────────
mkdir -p "$EXP_ROOT"

# ── 2. 复制模板文件 ──────────────────────────────────────────
echo "📋 复制模板文件..."
cp "$SKILL_DIR/assets/conf_baseline.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/conf_combined_factors.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/conf_single_factor.yaml" "$EXP_ROOT/"
cp "$SKILL_DIR/assets/read_exp_res.py" "$EXP_ROOT/"

# 复制脚本（含错误知识库管理脚本 collect_error.py）
for script in gen_daily_pv.py validate_factor.py merge_factors.py \
              analyze_results.py update_sota.py run_backtest.sh collect_error.py \
              run_single_backtest.sh run_round.sh run_baseline.sh \
              common.sh default_features.py; do
    cp "$SKILL_DIR/scripts/$script" "$EXP_ROOT/"
done

# ── 3. 初始化 SOTA 记录 ─────────────────────────────────────
cat > "$EXP_ROOT/sota_record.json" << 'EOF'
{
  "round": 0,
  "sota_factors": [],
  "sota_metrics": null,
  "history": []
}
EOF

echo "  ✅ 文件复制完成"

# ── 4. 生成数据文件 ──────────────────────────────────────────
echo ""
echo "📊 在 Docker 中生成数据文件 (daily_pv.h5 + daily_pv_debug.h5)..."
echo "   这可能需要几分钟..."

if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "local_qlib:latest"; then
    echo "❌ Docker 镜像 local_qlib:latest 不存在"
    echo "   请先构建: docker build -t local_qlib:latest -f rdagent/scenarios/qlib/docker/Dockerfile rdagent/scenarios/qlib/docker/"
    exit 1
fi

docker run --rm \
  -v "$EXP_ROOT":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/qlib/data":/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && python gen_daily_pv.py"

# 验证
if [ ! -f "$EXP_ROOT/daily_pv.h5" ]; then
    echo "❌ daily_pv.h5 生成失败"
    exit 1
fi
if [ ! -f "$EXP_ROOT/daily_pv_debug.h5" ]; then
    echo "❌ daily_pv_debug.h5 生成失败"
    exit 1
fi

echo "  ✅ daily_pv.h5 ($(du -h "$EXP_ROOT/daily_pv.h5" | cut -f1))"
echo "  ✅ daily_pv_debug.h5 ($(du -h "$EXP_ROOT/daily_pv_debug.h5" | cut -f1))"

# ── 5. 配置信息 ──────────────────────────────────────────────
# YAML 模板使用 Jinja2 变量，qrun 从环境变量读取参数（source .env 后自动可用）。
if [ -f "$EXP_ROOT/data_end_date.txt" ]; then
    DATA_END_DATE="$(cat "$EXP_ROOT/data_end_date.txt" | tr -d '[:space:]')"
    echo ""
    echo "📅 数据结束日期: $DATA_END_DATE（参考信息，保存在 data_end_date.txt）"
    echo "   如需指定 test_end，编辑项目根目录的 .env 中 test_end 字段"
    echo "   默认 test_end=null 表示 Qlib 自动使用数据最后一天"
fi

# ── 6. 完成 ──────────────────────────────────────────────────
echo ""
echo "🎉 工作空间初始化完成!"
echo ""
echo "📁 目录结构:"
echo "   $EXP_ROOT/"
echo "   ├── daily_pv.h5               ← 全量数据 (所有轮次共用)"
echo "   ├── daily_pv_debug.h5         ← 调试数据 (快速验证用)"
echo "   ├── conf_baseline.yaml        ← Qlib 基线回测配置 (Jinja2 模板)"
echo "   ├── conf_combined_factors.yaml← Qlib 合并因子回测配置 (Jinja2 模板)"
echo "   ├── conf_single_factor.yaml   ← 单因子独立回测配置 (Jinja2 模板)"
echo "   ├── read_exp_res.py           ← 回测结果提取"
echo "   ├── validate_factor.py        ← 因子快速验证"
echo "   ├── merge_factors.py          ← 因子合并+去重 (支持 --single 单因子模式)"
echo "   ├── run_backtest.sh           ← 合并因子回测"
echo "   ├── run_single_backtest.sh    ← 单因子独立回测"
echo "   ├── run_round.sh              ← 一键编排（单因子回测→合并回测→分析）"
echo "   ├── run_baseline.sh           ← 静态基线回测（可手动重跑）"
echo "   ├── analyze_results.py        ← 结果分析+对比SOTA (支持 --factor-dir)"
echo "   ├── update_sota.py            ← 更新SOTA记录"
echo "   ├── sota_record.json          ← SOTA 追踪（动态基线）"
echo "   └── baseline_record.json      ← 静态基线（当前 ACTIVE_FEATURE_SET）"
echo ""
echo "ℹ️  回测参数统一在项目根目录 .env 中配置，qrun 自动读取环境变量"

# ── 7. 生成静态基线 ──────────────────────────────────────────
echo ""
echo "📏 运行静态基线回测（当前 ACTIVE_FEATURE_SET，作为绝对参照）..."
BASELINE_SCRIPT="$(dirname "${BASH_SOURCE[0]}")/run_baseline.sh"
if [ -f "$BASELINE_SCRIPT" ]; then
    if bash "$BASELINE_SCRIPT" "$EXP_ROOT"; then
        echo "  ✅ 基线已保存: $EXP_ROOT/baseline_record.json"
    else
        echo "  ⚠️ 基线回测失败（不阻塞，可稍后 bash \"$EXP_ROOT/run_baseline.sh\" \"$EXP_ROOT\" 重试）"
    fi
else
    echo "  ⚠️ run_baseline.sh 不存在，跳过基线回测"
fi

echo ""
echo "下一步: 创建 round_1/ 目录并开始写因子代码"
echo "   mkdir -p $EXP_ROOT/round_1/<factor_name>"
echo ""
echo "EXP_ROOT=$EXP_ROOT"
