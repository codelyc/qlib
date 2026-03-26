#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# fin-model 公共函数库 — 所有脚本 source 此文件
#
# 用法（在其他脚本开头）:
#   source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
#
# 提供:
#   - _load_env()     从当前目录逐级向上查找并加载 .env
#   - _require_var()  检查必需变量，缺失则报错退出
#   - 加载后可用变量: PROJECT_ROOT, MODEL_SKILL_DIR, QLIB_DATA_DIR 等
# ═══════════════════════════════════════════════════════════════

_load_env() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.env" ]; then
            set -a; source "$dir/.env"; set +a
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

_require_var() {
    local var_name="$1"
    local description="${2:-}"
    local val=""
    eval "val=\${$var_name:-}"
    if [ -z "$val" ]; then
        echo "❌ 必需变量 $var_name 未设置${description:+ ($description)}"
        return 1
    fi
}

# ── 自动加载 .env ────────────────────────────────────────────
_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! _load_env "$_COMMON_DIR"; then
    echo ""
    echo "❌ 找不到 .env 文件（从 $_COMMON_DIR 向上搜索到根目录）"
    echo ""
    echo "请在项目根目录创建 .env 文件:"
    echo "  cp .env.template .env"
    echo "  vim .env   # 填写 PROJECT_ROOT 等本机路径"
    echo ""
    echo "必需变量:"
    echo "  PROJECT_ROOT        - 项目根目录绝对路径"
    echo "  QLIB_DATA_DIR       - Qlib 数据目录（含 features/ calendars/ instruments/）"
    echo "  MODEL_EXP_ROOT      - 模型优化工作区路径"
    echo "  DOCKER_IMAGE        - Docker 镜像名"
    echo "  train_start/end ... - 回测日期参数（小写，与 YAML 模板对应）"
    echo ""
    exit 1
fi

# ── 验证关键变量 ─────────────────────────────────────────────
_missing=0
_require_var PROJECT_ROOT "项目根目录"         || _missing=1
_require_var QLIB_DATA_DIR "Qlib 数据目录"     || _missing=1

if [ "$_missing" -eq 1 ]; then
    echo ""
    echo "请检查 .env 文件中以上变量是否已正确设置"
    exit 1
fi

if [ ! -d "$PROJECT_ROOT" ]; then
    echo "❌ PROJECT_ROOT 目录不存在: $PROJECT_ROOT"
    exit 1
fi

# ── 解析 Qlib 基础特征 ───────────────────────────────────────
if [ -n "${ACTIVE_FEATURE_SET:-}" ] && [ -f "$_COMMON_DIR/default_features.py" ]; then
    eval "$("$PYTHON_BIN" "$_COMMON_DIR/default_features.py" "$ACTIVE_FEATURE_SET")"
fi

# ── 派生变量（兜底）─────────────────────────────────────────
MODEL_SKILL_DIR="${MODEL_SKILL_DIR:-$PROJECT_ROOT/.github/skills/fin-model}"
MODEL_EXP_ROOT="${MODEL_EXP_ROOT:-$PROJECT_ROOT/factor_workspace/model_optimization}"
IMAGE="${DOCKER_IMAGE:-local_qlib:latest}"
SHM_SIZE="${DOCKER_SHM_SIZE:-16g}"
