#!/bin/bash
# replay.sh — 本地复刻 AI 生成的因子工作区（纯 conda，无 Docker）
#
# 功能:
#   1. 检查/安装 conda（阿里镜像）
#   2. 创建/复用 conda 环境 qlib_env，安装 qlib 及依赖
#   3. 自动发现 factor_workspace/ 工作区
#   4. 遍历所有 round_*/，重新跑每个因子的 factor.py
#   5. 合并因子，生成 combined_factors_df.parquet
#   6. 打印后续回测 & 分析命令，由用户手动执行
#
# 用法:
#   bash qlib/replay.sh
#   EXP_ROOT=/path/to/xxx bash qlib/replay.sh   # 指定工作区（多个工作区时使用）
#
# ⚠️  不要用 sudo 执行！

set -euo pipefail

# ══════════════════════════════════════════════════════════════
# 颜色 & 工具函数
# ══════════════════════════════════════════════════════════════
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${GREEN}  ✅ $*${RESET}"; }
warn()    { echo -e "${YELLOW}  ⚠️  $*${RESET}"; }
error()   { echo -e "${RED}  ❌ $*${RESET}"; }
step()    { echo -e "\n${BOLD}${BLUE}════════════════════════════════════════════${RESET}"; \
            echo -e "${BOLD}${BLUE}  $*${RESET}"; \
            echo -e "${BOLD}${BLUE}════════════════════════════════════════════${RESET}"; }

if [ "$(id -u)" -eq 0 ]; then
    error "请不要用 sudo 执行此脚本！sudo 会改变 HOME 目录和 Python 环境。"
    error "正确用法: bash qlib/replay.sh"
    exit 1
fi

# ══════════════════════════════════════════════════════════════
# 0. 路径定位
# ══════════════════════════════════════════════════════════════
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
QLIB_SRC="$SCRIPT_DIR"   # replay.sh 在 qlib/ 里，qlib 源码就是同级目录

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║   🔁  因子工作区本地复刻脚本  replay.sh      ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
echo -e "   项目根: ${CYAN}$PROJECT_ROOT${RESET}"
echo -e "   qlib源码: ${CYAN}$QLIB_SRC${RESET}"

# ══════════════════════════════════════════════════════════════
# Step 1：检查 / 安装 conda
# ══════════════════════════════════════════════════════════════
step "Step 1/5  检查 conda"

# 尝试从常见路径加载 conda（应对未 source ~/.bashrc 的情况）
_try_load_conda() {
    for _p in \
        "$HOME/miniconda3/etc/profile.d/conda.sh" \
        "$HOME/anaconda3/etc/profile.d/conda.sh" \
        "/opt/conda/etc/profile.d/conda.sh" \
        "/usr/local/conda/etc/profile.d/conda.sh" \
        "/opt/miniconda3/etc/profile.d/conda.sh"; do
        if [ -f "$_p" ]; then
            # shellcheck source=/dev/null
            source "$_p"
            return 0
        fi
    done
    return 1
}

if ! command -v conda &>/dev/null; then
    _try_load_conda || true
fi

if ! command -v conda &>/dev/null; then
    warn "未检测到 conda，开始自动安装 Miniconda（阿里镜像）..."
    MINICONDA_URL="https://mirrors.aliyun.com/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh"
    MINICONDA_SH="/tmp/miniconda_install_$$.sh"

    if command -v wget &>/dev/null; then
        wget -q --show-progress -O "$MINICONDA_SH" "$MINICONDA_URL"
    elif command -v curl &>/dev/null; then
        curl -L --progress-bar -o "$MINICONDA_SH" "$MINICONDA_URL"
    else
        error "未找到 wget/curl，无法下载 Miniconda，请手动安装后重试。"
        exit 1
    fi

    bash "$MINICONDA_SH" -b -p "$HOME/miniconda3"
    rm -f "$MINICONDA_SH"
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
    conda init bash 2>/dev/null || true
    info "Miniconda 安装完成: $HOME/miniconda3"
else
    info "conda 已安装: $(conda --version)"
fi

# ══════════════════════════════════════════════════════════════
# Step 2：配置阿里镜像源
# ══════════════════════════════════════════════════════════════
step "Step 2/5  配置镜像源（conda 清华 / pip 阿里）"

if [ ! -f "$HOME/.condarc" ] || ! grep -q "tsinghua\|tuna" "$HOME/.condarc" 2>/dev/null; then
    cat > "$HOME/.condarc" << 'EOF'
channels:
  - defaults
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/msys2
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
show_channel_urls: true
EOF
    info "~/.condarc 已写入清华 conda 镜像（阿里 anaconda 镜像已停服）"
else
    info "~/.condarc 已存在清华镜像配置，跳过"
fi

PIP_INDEX="https://mirrors.aliyun.com/pypi/simple/"
PIP_HOST="mirrors.aliyun.com"

# ══════════════════════════════════════════════════════════════
# Step 3：创建/复用 conda 环境 + 安装依赖
# ══════════════════════════════════════════════════════════════
step "Step 3/5  准备 conda 环境 qlib_env (Python 3.8)"

ENV_NAME="qlib_env"

if conda env list 2>/dev/null | grep -q "^${ENV_NAME}[[:space:]]"; then
    info "环境 $ENV_NAME 已存在，跳过创建"
else
    echo -e "  🔧 创建环境 $ENV_NAME (Python 3.8)..."
    conda create -n "$ENV_NAME" python=3.8 -y
    info "环境创建完成"
fi

# 统一用 conda run 执行，避免 activate 的 shell 兼容性问题
PYEXEC="conda run --no-capture-output -n $ENV_NAME python"
PIPEXEC="conda run --no-capture-output -n $ENV_NAME pip"

# 从本地 qlib 源码安装（pyproject.toml 自动管理所有依赖），每次都执行确保最新
# pip install -e 在已安装时只做版本检查，速度很快
echo ""
echo -e "  📦 安装 qlib 及其依赖（来源: ${CYAN}$QLIB_SRC/pyproject.toml${RESET}）..."
$PIPEXEC install -e "$QLIB_SRC" \
    -i "$PIP_INDEX" --trusted-host "$PIP_HOST" \
    --quiet
info "qlib 安装/更新完成 (源码: $QLIB_SRC)"

# 补充 pyproject.toml 未声明但运行时必需的包：
#   - tables:    pandas read_hdf / to_hdf (HDF5) 支持
#   - pandas>=2.0: daily_pv.h5 由新版 pandas 写入（kind='datetime64[ns]'），
#                  pandas 1.x 无法读取，需要 2.0+
echo ""
echo -e "  📦 补充安装运行时依赖..."
$PIPEXEC install -q \
    "tables" \
    "pandas>=2.0" \
    -i "$PIP_INDEX" --trusted-host "$PIP_HOST"
info "tables / pandas>=2.0 安装完成"

QLIB_VER=$($PYEXEC -c "import qlib; print(qlib.__version__)" 2>/dev/null || echo "dev")
PANDAS_VER=$($PYEXEC -c "import pandas; print(pandas.__version__)" 2>/dev/null || echo "?")
info "环境就绪  qlib=${QLIB_VER}  pandas=${PANDAS_VER}"

# ══════════════════════════════════════════════════════════════
# Step 4：检查并修复 Qlib 数据目录结构
# ══════════════════════════════════════════════════════════════
step "Step 4/6  检查并修复 Qlib 数据目录结构"

CN_DATA="$HOME/.qlib/qlib_data/cn_data"
if [ ! -d "$CN_DATA" ]; then
    warn "数据目录 $CN_DATA 不存在，回测可能会失败！"
else
    # 修复 instruments
    if [ ! -d "$CN_DATA/instruments" ]; then
        echo -e "  🔧 创建 instruments/ 软链接..."
        mkdir -p "$CN_DATA/instruments"
        for f in "$CN_DATA"/*.txt; do
            [ ! -f "$f" ] && continue
            fname=$(basename "$f")
            [[ "$fname" == day*.txt ]] && continue
            ln -sf "../$fname" "$CN_DATA/instruments/$fname"
        done
        info "instruments/ 结构修复完成"
    else
        info "instruments/ 结构已正确"
    fi

    # 修复 calendars
    if [ ! -d "$CN_DATA/calendars" ]; then
        echo -e "  🔧 创建 calendars/ 软链接..."
        mkdir -p "$CN_DATA/calendars"
        for f in "$CN_DATA"/day*.txt; do
            [ ! -f "$f" ] && continue
            fname=$(basename "$f")
            ln -sf "../$fname" "$CN_DATA/calendars/$fname"
        done
        info "calendars/ 结构修复完成"
    else
        info "calendars/ 结构已正确"
    fi
fi

# ══════════════════════════════════════════════════════════════
# Step 5：自动发现 factor_workspace/
# ══════════════════════════════════════════════════════════════
step "Step 5/6  发现因子工作区"

FW_BASE="$PROJECT_ROOT/factor_workspace"

if [ ! -d "$FW_BASE" ]; then
    error "找不到 $FW_BASE，请确认项目结构正确"
    exit 1
fi

# 如果外部未指定 EXP_ROOT，自动发现
if [ -z "${EXP_ROOT:-}" ]; then
    subdirs=()
    while IFS= read -r d; do
        subdirs+=("$d")
    done < <(find "$FW_BASE" -mindepth 1 -maxdepth 1 -type d | sort)

    count=${#subdirs[@]}

    if [ "$count" -eq 0 ]; then
        error "$FW_BASE 下没有工作区子目录"
        exit 1
    elif [ "$count" -eq 1 ]; then
        EXP_ROOT="${subdirs[0]}"
        info "自动使用工作区: $EXP_ROOT"
    else
        warn "发现多个工作区，请通过 EXP_ROOT 指定后重新运行："
        echo ""
        for d in "${subdirs[@]}"; do
            echo -e "      ${CYAN}EXP_ROOT=$d bash $0${RESET}"
        done
        echo ""
        exit 1
    fi
else
    EXP_ROOT="$(cd "$EXP_ROOT" && pwd)"
    info "使用指定工作区: $EXP_ROOT"
fi

# 检查 daily_pv.h5
if [ ! -f "$EXP_ROOT/daily_pv.h5" ]; then
    error "找不到 $EXP_ROOT/daily_pv.h5（全量数据文件），无法运行因子"
    exit 1
fi
info "全量数据文件: $EXP_ROOT/daily_pv.h5 ($(du -h "$EXP_ROOT/daily_pv.h5" | cut -f1))"

# ══════════════════════════════════════════════════════════════
# Step 6：遍历 round_*/，重跑因子 + 合并
# ══════════════════════════════════════════════════════════════
step "Step 6/6  重跑因子 & 合并"

# 收集所有 round_* 目录
round_dirs=()
while IFS= read -r d; do
    round_dirs+=("$d")
done < <(find "$EXP_ROOT" -mindepth 1 -maxdepth 1 -type d -name "round_*" | sort)

if [ ${#round_dirs[@]} -eq 0 ]; then
    error "未找到任何 round_* 目录（路径: $EXP_ROOT）"
    exit 1
fi

echo -e "  共发现 ${#round_dirs[@]} 个轮次: $(basename -a "${round_dirs[@]}" | tr '\n' ' ')"

# 提前一次性清除所有 root 所有的旧文件/目录（Docker 生成的）：
# 如果有权限问题，会在最后提示用户手动 sudo rm
root_paths=()
while IFS= read -r item; do
    owner=$(stat -c '%U' "$item" 2>/dev/null || echo "unknown")
    [ "$owner" = "root" ] && root_paths+=("$item")
done < <(
    find "${round_dirs[@]}" -maxdepth 4 2>/dev/null \
        \( -name "result.h5" -o -name "mlruns" -o -name "workspace" -o -name "home" -o -name "qlib_res.csv" -o -name "ret.pkl" \)
)

if [ ${#root_paths[@]} -gt 0 ]; then
    echo ""
    warn "发现 ${#root_paths[@]} 个由 Docker(root) 生成的旧文件/目录："
    for item in "${root_paths[@]}"; do
        echo -e "      $item"
    done
    echo ""
    echo -e "  🔧 尝试清理..."
    # 尝试不用密码的 sudo 清理，如果失败就在结尾提示
    sudo -n rm -rf "${root_paths[@]}" 2>/dev/null || true
    
    # 检查是否清理成功
    still_exists=0
    for item in "${root_paths[@]}"; do
        [ -e "$item" ] && still_exists=1
    done
    if [ "$still_exists" -eq 1 ]; then
        warn "部分 root 文件无法自动清理，将在最后给出清理命令"
        SUDO_RM_CMD="sudo rm -rf ${root_paths[*]}"
    else
        info "旧文件/目录已清除"
        SUDO_RM_CMD=""
    fi
else
    SUDO_RM_CMD=""
fi

SUCCESS_ROUNDS=()  # 合并成功的 round_dir 列表

for ROUND_DIR in "${round_dirs[@]}"; do
    ROUND_NAME="$(basename "$ROUND_DIR")"
    ROUND_NUM="${ROUND_NAME#round_}"

    echo ""
    echo -e "  ${BOLD}📂 处理 $ROUND_NAME ...${RESET}"

    # ── 5a. 遍历因子目录，重跑 factor.py ───────────────────
    factor_ok=0
    factor_fail=0

    while IFS= read -r factor_dir; do
        # 只处理含 factor.py 的子目录（跳过 mlruns/ workspace/ 等）
        [ -f "$factor_dir/factor.py" ] || continue

        factor_name="$(basename "$factor_dir")"
        echo ""
        echo -e "    ${CYAN}▶ 因子: $factor_name${RESET}"

        # 复制全量数据（覆盖旧的）
        cp "$EXP_ROOT/daily_pv.h5" "$factor_dir/daily_pv.h5"
        echo -e "      ✅ daily_pv.h5 已复制"

            # 执行 factor.py，cwd 必须是 factor_dir（factor.py 用相对路径读 daily_pv.h5）
        # 注: daily_pv.h5 由旧版 Docker 生成，index kind='datetime64[ns]'（带单位后缀），
        #     需要 monkey-patch pandas pytables 使其能正常读取
        set +e
        conda run --no-capture-output -n "$ENV_NAME" \
            --cwd "$factor_dir" \
            python -c "
import pandas.io.pytables as _pt
_orig = _pt._unconvert_index
def _patched(values, kind, encoding=None, errors='strict'):
    # 兼容旧格式：datetime64[ns] → datetime64
    if isinstance(kind, str) and kind.startswith('datetime64'):
        kind = 'datetime64'
    return _orig(values, kind, encoding=encoding, errors=errors)
_pt._unconvert_index = _patched
import runpy
runpy.run_path('factor.py', run_name='__main__')
" \
            2>&1 | sed 's/^/      /'
        exit_code=${PIPESTATUS[0]}
        set -e

        if [ "$exit_code" -eq 0 ]; then
            info "result.h5 生成成功 ($factor_name)"
            factor_ok=$((factor_ok + 1))
        else
            error "factor.py 执行失败，跳过 ($factor_name)"
            factor_fail=$((factor_fail + 1))
        fi

    done < <(find "$ROUND_DIR" -mindepth 1 -maxdepth 1 -type d | sort)

    echo ""
    echo -e "    因子执行结果: ${GREEN}✅ $factor_ok 成功${RESET}  ${RED}❌ $factor_fail 失败${RESET}"

    if [ "$factor_ok" -eq 0 ]; then
        warn "$ROUND_NAME 没有成功的因子，跳过合并"
        continue
    fi

    # ── 5b. 合并因子 ────────────────────────────────────────
    echo ""
    echo -e "    🔗 合并因子..."

    # 复刻模式：直接合并本轮因子，不做 SOTA IC 去重
    # （去重需 750万行×9对相关性计算，耗时极长；复刻无需去重）
    set +e
    conda run --no-capture-output -n "$ENV_NAME" \
        python "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
        2>&1 | sed 's/^/    /'
    merge_exit=${PIPESTATUS[0]}
    set -e

    if [ "$merge_exit" -ne 0 ]; then
        error "$ROUND_NAME 合并因子失败，跳过"
        continue
    fi
    info "combined_factors_df.parquet 已生成 ($ROUND_NAME)"

    # ── 5c. 复制并修正回测所需配置文件 ──────────────────
    cp "$EXP_ROOT/conf_combined_factors.yaml" "$ROUND_DIR/"
    cp "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/"
    
    # 修正回测时间（避免 Empty data from dataset 错误）
    # 将 start_time / train 统一改成 2009-01-01（因为我们的新因子最早的数据从 2009-01 开始）
    sed -i 's/"2008-01-01"/"2009-01-01"/g' "$ROUND_DIR/conf_combined_factors.yaml"
    
    info "conf_combined_factors.yaml + read_exp_res.py 已复制并修正时间 ($ROUND_NAME/)"

    SUCCESS_ROUNDS+=("$ROUND_DIR")
done

# ══════════════════════════════════════════════════════════════
# Step 6：打印后续命令（用户手动执行）
# ══════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${GREEN}║  🎉 因子计算 & 合并完成！                                   ║${RESET}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════════════╝${RESET}"

if [ ${#SUCCESS_ROUNDS[@]} -eq 0 ]; then
    warn "所有轮次均未成功，请检查上方错误信息"
    exit 1
fi

echo ""
echo -e "${BOLD}  下一步：激活环境后，按顺序执行以下命令完成回测和分析${RESET}"
echo ""

if [ -n "${SUDO_RM_CMD:-}" ]; then
    echo -e "  ${RED}${BOLD}# ⚠️ 必须先清除 Docker 遗留的 root 文件，否则回测会报 PermissionError！${RESET}"
    echo -e "  ${CYAN}$SUDO_RM_CMD${RESET}"
    echo ""
fi

echo -e "  ${YELLOW}# 先激活 conda 环境${RESET}"
echo -e "  ${CYAN}conda activate $ENV_NAME${RESET}"

for ROUND_DIR in "${SUCCESS_ROUNDS[@]}"; do
    ROUND_NAME="$(basename "$ROUND_DIR")"
    ROUND_NUM="${ROUND_NAME#round_}"

    echo ""
    echo -e "  ${BOLD}── $ROUND_NAME ──────────────────────────────────────────────${RESET}"
    echo ""
    echo -e "  ${YELLOW}# 1. 运行回测${RESET}"
    echo -e "  ${YELLOW}#    （模型/数据/参数已在 yaml 里写好，qrun 一条命令完成训练+回测）${RESET}"
    echo -e "  ${CYAN}cd $ROUND_DIR${RESET}"
    echo -e "  ${CYAN}sed -i 's/2008-01-01/2010-01-01/g' conf_combined_factors.yaml${RESET}"
    echo -e "  ${CYAN}export MLFLOW_TRACKING_URI=\"file://\$(pwd)/mlruns_local\"${RESET}"
    echo -e "  ${CYAN}qrun conf_combined_factors.yaml${RESET}"
    echo -e "  ${CYAN}python read_exp_res.py${RESET}"
    echo ""
    echo -e "  ${YELLOW}# 2. 分析结果（对比历史 SOTA）${RESET}"
    echo -e "  ${CYAN}python $EXP_ROOT/analyze_results.py \\"
    echo -e "    $ROUND_DIR \\"
    echo -e "    --sota-file $EXP_ROOT/sota_record.json${RESET}"
    echo ""
    echo -e "  ${YELLOW}# 3. 更新 SOTA 记录${RESET}"
    echo -e "  ${CYAN}python $EXP_ROOT/update_sota.py \\"
    echo -e "    $EXP_ROOT $ROUND_DIR $ROUND_NUM${RESET}"
done

echo ""
echo -e "  ${BOLD}── 完成后查看报告 ────────────────────────────────────────────${RESET}"
echo ""
echo -e "  ${YELLOW}# 查看汇总报告${RESET}"
echo -e "  ${CYAN}cat $EXP_ROOT/summary.md${RESET}"
echo ""
echo -e "  ${YELLOW}# 查看最新一轮详细报告${RESET}"
echo -e "  ${CYAN}cat ${SUCCESS_ROUNDS[-1]}/report.md${RESET}"
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════════${RESET}"
echo ""
