#!/bin/bash
# 初始化因子研发工作空间
# 用法: bash init_workspace.sh [workspace_name]
#
# 产出:
#   $EXP_ROOT/ 包含所有需要的模板和脚本
#   daily_pv.h5 + daily_pv_debug.h5 在 Docker 中生成

set -euo pipefail

# ── 0. 定位项目根目录（带 fallback）──────────────────────────
PROJECT_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SKILL_DIR="$PROJECT_ROOT/.github/skills/fin-factor"

# 验证路径是否正确
if [ ! -d "$SKILL_DIR/scripts" ] || [ ! -d "$SKILL_DIR/assets" ]; then
    echo "⚠️  路径自动检测失败，尝试 git rev-parse ..."
    PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    SKILL_DIR="$PROJECT_ROOT/.github/skills/fin-factor"
    if [ ! -d "$SKILL_DIR/scripts" ]; then
        echo "❌ 无法定位项目根目录"
        echo "   请在项目目录下运行，或传入绝对路径"
        exit 1
    fi
fi

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
cp "$SKILL_DIR/assets/read_exp_res.py" "$EXP_ROOT/"

# 复制脚本
for script in gen_daily_pv.py validate_factor.py merge_factors.py \
              analyze_results.py update_sota.py run_backtest.sh; do
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
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
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

# ── 5. 动态替换 YAML 中的日期占位符 ─────────────────────────
if [ ! -f "$EXP_ROOT/data_end_date.txt" ]; then
    echo "❌ data_end_date.txt 未生成，无法替换 YAML 日期"
    exit 1
fi

DATA_END_DATE="$(cat "$EXP_ROOT/data_end_date.txt" | tr -d '[:space:]')"
echo ""
echo "📅 替换 YAML 日期占位符 → $DATA_END_DATE ..."
for yaml_file in "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/conf_baseline.yaml"; do
    if [ -f "$yaml_file" ]; then
        sed -i "s/__DATA_END_DATE__/$DATA_END_DATE/g" "$yaml_file"
        # 验证替换完成
        if grep -q "__DATA_END_DATE__" "$yaml_file"; then
            echo "  ⚠️ $yaml_file 中仍有未替换的占位符"
        else
            echo "  ✅ $(basename "$yaml_file") → end_time=$DATA_END_DATE"
        fi
    fi
done

# ── 6. 完成 ──────────────────────────────────────────────────
echo ""
echo "🎉 工作空间初始化完成!"
echo ""
echo "📁 目录结构:"
echo "   $EXP_ROOT/"
echo "   ├── daily_pv.h5               ← 全量数据 (所有轮次共用)"
echo "   ├── daily_pv_debug.h5         ← 调试数据 (快速验证用)"
echo "   ├── conf_baseline.yaml        ← Qlib 基线回测配置"
echo "   ├── conf_combined_factors.yaml← Qlib 合并因子回测配置"
echo "   ├── read_exp_res.py           ← 回测结果提取"
echo "   ├── validate_factor.py        ← 因子快速验证"
echo "   ├── merge_factors.py          ← 因子合并+去重"
echo "   ├── run_backtest.sh           ← 一键回测"
echo "   ├── analyze_results.py        ← 结果分析+对比SOTA"
echo "   ├── update_sota.py            ← 更新SOTA记录"
echo "   └── sota_record.json          ← SOTA 追踪"
echo ""
echo "下一步: 创建 round_1/ 目录并开始写因子代码"
echo "   mkdir -p $EXP_ROOT/round_1/<factor_name>"
echo ""
echo "EXP_ROOT=$EXP_ROOT"
