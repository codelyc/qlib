#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# fin-quant 联合优化环境 一键初始化 / 检查 / 修复
# ═══════════════════════════════════════════════════════════════
# 用法: bash main_setup.sh
#
# 本脚本在 fin-factor 和 fin-model 的环境检查基础上，
# 额外验证两个子 skill 都就绪、GPU 可用。
#
# 流程：
#   1. 运行 fin-factor 的 main_setup.sh（Docker + 镜像 + 数据 + Python）
#   2. 验证 fin-model 相关依赖（PyTorch + GPU）
#   3. 验证子 skill 目录完整性
#   4. 验证 fin-quant 自身脚本
#
# ⚠️  不要用 sudo 执行！

echo "════════════════════════════════════════════════════════"
echo "  🔍 联合优化环境 Setup (fin-quant)"
echo "════════════════════════════════════════════════════════"
echo ""

# ── 0. 防止 sudo ─────────────────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then
    echo "❌ 请不要用 sudo 执行此脚本！"
    exit 1
fi

# 加载公共配置
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PASS=0
FAIL=0
WARN=0

check_pass()  { echo "  ✅ $1"; PASS=$((PASS + 1)); }
check_fail()  { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
check_warn()  { echo "  ⚠️  $1"; WARN=$((WARN + 1)); }

# ════════════════════════════════════════════════════════════
# 阶段 1: 调用 fin-factor 的环境检查
# ════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📦 阶段 1: 基础环境 (调用 fin-factor)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

FACTOR_SETUP="$SKILL_DIR/scripts/main_setup.sh"
if [ -f "$FACTOR_SETUP" ]; then
    bash "$FACTOR_SETUP"
    FACTOR_EXIT=$?
    if [ "$FACTOR_EXIT" -ne 0 ]; then
        echo ""
        echo "❌ fin-factor 环境检查失败 (exit: $FACTOR_EXIT)"
        echo "   请先修复 fin-factor 的问题，然后重新运行本脚本。"
        exit 1
    fi
    check_pass "fin-factor 环境就绪"
else
    check_fail "fin-factor main_setup.sh 不存在: $FACTOR_SETUP"
fi

# ════════════════════════════════════════════════════════════
# 阶段 2: 模型相关检查 (PyTorch + GPU)
# ════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🤖 阶段 2: 模型环境检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# PyTorch 检查
echo "1️⃣  PyTorch"
if $PYTHON_BIN -c "import torch; print(f'torch {torch.__version__}')" 2>/dev/null; then
    check_pass "PyTorch 可用"

    # CUDA 检查
    CUDA_AVAIL=$($PYTHON_BIN -c "import torch; print(torch.cuda.is_available())" 2>/dev/null)
    if [ "$CUDA_AVAIL" = "True" ]; then
        GPU_NAME=$($PYTHON_BIN -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null)
        check_pass "CUDA 可用: $GPU_NAME"
    else
        check_warn "CUDA 不可用 (模型训练将使用 CPU，速度较慢)"
    fi
else
    check_fail "PyTorch 未安装"
    echo "     建议: $PYTHON_BIN -m pip install torch"
fi

# Docker GPU 检查
echo ""
echo "2️⃣  Docker GPU"
if docker run --rm --gpus all "$IMAGE" nvidia-smi &>/dev/null; then
    check_pass "Docker GPU 可用"
else
    check_warn "Docker GPU 不可用 (模型将在 CPU 训练)"
    echo "     如需 GPU: sudo apt install nvidia-container-toolkit && sudo systemctl restart docker"
fi

# ════════════════════════════════════════════════════════════
# 阶段 3: 子 skill 目录完整性
# ════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📂 阶段 3: 子 Skill 目录检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# fin-factor 脚本
echo "3️⃣  fin-factor 脚本"
_factor_ok=1
for script in validate_factor.py merge_factors.py run_round.sh run_backtest.sh \
              run_single_backtest.sh analyze_results.py collect_error.py \
              gen_daily_pv.py default_features.py; do
    if [ ! -f "$SKILL_DIR/scripts/$script" ]; then
        check_fail "缺失: $SKILL_DIR/scripts/$script"
        _factor_ok=0
    fi
done
[ "$_factor_ok" -eq 1 ] && check_pass "fin-factor 脚本完整 ($(ls "$SKILL_DIR/scripts/" | wc -l) files)"

# fin-model 脚本
echo ""
echo "4️⃣  fin-model 脚本"
_model_ok=1
for script in validate_model.py run_backtest.sh run_round.sh \
              analyze_results.py collect_error.py; do
    if [ ! -f "$MODEL_SKILL_DIR/scripts/$script" ]; then
        check_fail "缺失: $MODEL_SKILL_DIR/scripts/$script"
        _model_ok=0
    fi
done
[ "$_model_ok" -eq 1 ] && check_pass "fin-model 脚本完整 ($(ls "$MODEL_SKILL_DIR/scripts/" | wc -l) files)"

# YAML 配置模板
echo ""
echo "5️⃣  YAML 配置模板"
_yaml_ok=1
for yaml in "$SKILL_DIR/assets/conf_baseline.yaml" \
            "$SKILL_DIR/assets/conf_combined_factors.yaml" \
            "$MODEL_SKILL_DIR/assets/conf_baseline_model.yaml" \
            "$MODEL_SKILL_DIR/assets/conf_sota_model.yaml" \
            "$QUANT_SKILL_DIR/assets/conf_factor_with_sota_model.yaml"; do
    if [ ! -f "$yaml" ]; then
        check_fail "缺失: $yaml"
        _yaml_ok=0
    fi
done
[ "$_yaml_ok" -eq 1 ] && check_pass "YAML 模板完整 (因子3 + 模型2 + 联合1)"

# ════════════════════════════════════════════════════════════
# 阶段 4: fin-quant 自身脚本
# ════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🔄 阶段 4: fin-quant 自身检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "6️⃣  fin-quant 脚本"
_quant_ok=1
for script in action_advisor.py quant_trace.py prepare_cross_data.py \
              run_quant_round.sh update_quant_sota.py; do
    if [ ! -f "$QUANT_SKILL_DIR/scripts/$script" ]; then
        check_fail "缺失: $QUANT_SKILL_DIR/scripts/$script"
        _quant_ok=0
    fi
done
[ "$_quant_ok" -eq 1 ] && check_pass "fin-quant 脚本完整"

# numpy 检查（action_advisor.py 需要）
echo ""
echo "7️⃣  Python 依赖 (numpy for Bandit)"
if $PYTHON_BIN -c "import numpy" &>/dev/null; then
    check_pass "numpy 可用"
else
    check_fail "numpy 未安装 (Bandit 需要)"
    echo "     修复: $PYTHON_BIN -m pip install numpy"
fi

# ════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════"
SUMMARY="✅ $PASS 通过"
[ "$FAIL" -gt 0 ] && SUMMARY="$SUMMARY  ❌ $FAIL 失败"
[ "$WARN" -gt 0 ] && SUMMARY="$SUMMARY  ⚠️  $WARN 警告"
echo "  📊 $SUMMARY"
echo "════════════════════════════════════════════════════════"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "❌ 有 $FAIL 项失败，请修复后重新运行:"
    echo "   bash $QUANT_SKILL_DIR/scripts/main_setup.sh"
    exit 1
else
    echo ""
    echo "🎉 联合优化环境就绪！"
    echo ""
    echo "下一步: 初始化工作空间"
    echo "   bash $QUANT_SKILL_DIR/scripts/init_workspace.sh [名称]"
    exit 0
fi
