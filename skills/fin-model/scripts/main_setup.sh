#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# fin-model 模型优化环境 一键初始化 / 检查 / 修复
# ═══════════════════════════════════════════════════════════════
# 用法: bash main_setup.sh
#
# 交互式流程：
#   1. 询问是否重置环境（默认 N，回车跳过）
#   2. 检查所有依赖并自动修复：
#      - Docker 守护进程
#      - Docker 镜像 ($DOCKER_IMAGE)
#      - Qlib 数据 (features/calendars/instruments)
#      - Python 环境 (pandas, tables, numpy, pyarrow, torch)
#
# ⚠️  不要用 sudo 执行！

echo "============================================"
echo "  🔍 模型优化环境 Setup (fin-model)"
echo "============================================"
echo ""

# ── 0. 防止 sudo 执行 ───────────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then
    echo "❌ 请不要用 sudo 执行此脚本！"
    echo "   sudo 会改变 HOME 目录和 Python 环境，导致检测不准确。"
    echo "   正确用法: bash $0"
    exit 1
fi

# 加载公共配置（自动定位 .env 并 source）
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

PASS=0
FAIL=0
WARN=0
FIXED=0

check_pass()  { echo "  ✅ $1"; PASS=$((PASS + 1)); }
check_fail()  { echo "  ❌ $1"; FAIL=$((FAIL + 1)); }
check_warn()  { echo "  ⚠️  $1"; WARN=$((WARN + 1)); }
check_fixed() { echo "  🔧 已修复: $1"; FIXED=$((FIXED + 1)); }

# ════════════════════════════════════════════════════════════
# 阶段 1: 询问是否重置环境
# ════════════════════════════════════════════════════════════
echo "📌 是否要重置环境？（删除 Docker 镜像 + Qlib 数据，然后重新构建/下载）"
echo "   适用于：环境损坏、想从头验证、切换数据版本"
echo ""
read -r -p "   重置环境? [y/N] (直接回车=不重置): " RESET_ANSWER
echo ""

if [[ "$RESET_ANSWER" =~ ^[Yy]$ ]]; then
    echo "🗑️  开始重置环境 ..."
    echo ""

    # 删除 Docker 镜像
    if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "${IMAGE}"; then
        echo "  🗑️  删除 Docker 镜像 ${IMAGE} ..."
        docker rmi -f "${IMAGE}" 2>&1 | tail -2
        echo "  ✅ Docker 镜像已删除"
    else
        echo "  ⏭️  Docker 镜像不存在，跳过"
    fi

    # 删除 Qlib 数据
    QLIB_DATA_RESET="$QLIB_DATA_DIR"
    if [ -d "$QLIB_DATA_RESET" ] && [ -d "$QLIB_DATA_RESET/features" ]; then
        echo "  🗑️  删除 Qlib 数据: $QLIB_DATA_RESET ..."
        rm -rf "$QLIB_DATA_RESET"
        echo "  ✅ Qlib 数据已删除"
    else
        echo "  ⏭️  Qlib 数据不存在，跳过"
    fi

    echo ""
    echo "🗑️  重置完成！接下来自动检查 & 修复 ..."
    echo ""
else
    echo "⏭️  跳过重置，直接检查环境 ..."
    echo ""
fi

# ════════════════════════════════════════════════════════════
# 阶段 2: 检查 & 自动修复
# ════════════════════════════════════════════════════════════

# ── 1. Docker ────────────────────────────────────────────────
echo "1️⃣  Docker 守护进程"
if docker info &>/dev/null; then
    check_pass "Docker 运行中"
else
    check_fail "Docker 未运行"
    echo "     🔧 尝试启动 Docker ..."
    sudo systemctl start docker 2>/dev/null || sudo service docker start 2>/dev/null || true
    sleep 2
    if docker info &>/dev/null; then
        check_fixed "Docker 已启动"
    else
        echo "     ❌ 无法自动启动，请手动: sudo systemctl start docker"
    fi
fi

# ── 2. Docker 镜像 ──────────────────────────────────────────
echo ""
echo "2️⃣  Docker 镜像 (${IMAGE})"
if docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | grep -q "${IMAGE}"; then
    check_pass "${IMAGE} 存在"
else
    check_fail "${IMAGE} 不存在"
    # 从本 skill 自带的 Dockerfile 构建
    DOCKER_DIR="$MODEL_SKILL_DIR/docker"
    if [ ! -f "$DOCKER_DIR/Dockerfile" ]; then
        # fallback: 尝试 RD-Agent 的 Dockerfile
        DOCKER_DIR="$PROJECT_ROOT/RD-Agent/rdagent/scenarios/qlib/docker"
    fi
    if [ -f "$DOCKER_DIR/Dockerfile" ]; then
        echo "     🔧 构建镜像 (可能需要 5-10 分钟，下方显示实时进度) ..."
        echo "     Dockerfile: $DOCKER_DIR/Dockerfile"
        echo "     ────────────────────────────────"
        if docker build --progress=plain -t "${IMAGE}" -f "$DOCKER_DIR/Dockerfile" "$DOCKER_DIR" 2>&1; then
            echo "     ────────────────────────────────"
            check_fixed "${IMAGE} 构建完成"
        else
            echo "     ────────────────────────────────"
            echo "     ❌ 构建失败，请手动:"
            echo "        docker build -t ${IMAGE} -f $DOCKER_DIR/Dockerfile $DOCKER_DIR"
        fi
    else
        echo "     ❌ 找不到 Dockerfile"
        echo "     请手动构建: docker build -t ${IMAGE} -f $MODEL_SKILL_DIR/docker/Dockerfile $MODEL_SKILL_DIR/docker/"
    fi
fi

# ── 2.5. Docker GPU 支持 ────────────────────────────────────
echo ""
echo "2️⃣ .5  Docker GPU 支持"
if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
    _GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    check_pass "宿主机 GPU: ${_GPU_NAME:-检测到}"

    # 检查 nvidia-container-toolkit
    if dpkg -l 2>/dev/null | grep -q "nvidia-container-toolkit" || \
       rpm -qa 2>/dev/null | grep -q "nvidia-container-toolkit" || \
       command -v nvidia-container-runtime &>/dev/null; then
        check_pass "nvidia-container-toolkit 已安装"
    else
        check_fail "nvidia-container-toolkit 未安装"
        echo "     🔧 自动安装 nvidia-container-toolkit ..."

        # 添加 NVIDIA apt 仓库
        _TOOLKIT_OK=false
        if curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
            | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null \
          && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
            | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
            | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null 2>&1 \
          && sudo apt-get update -qq 2>/dev/null \
          && sudo apt-get install -y nvidia-container-toolkit 2>&1 | tail -3 \
          && sudo nvidia-ctk runtime configure --runtime=docker 2>/dev/null \
          && sudo systemctl restart docker 2>/dev/null; then
            sleep 2
            _TOOLKIT_OK=true
            check_fixed "nvidia-container-toolkit 安装完成"
        else
            echo "     ❌ 自动安装失败，请手动执行以下命令:"
            echo "        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg"
            echo "        curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list"
            echo "        sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit"
            echo "        sudo nvidia-ctk runtime configure --runtime=docker"
            echo "        sudo systemctl restart docker"
        fi
    fi

    # 验证 Docker 内能否访问 GPU
    if docker info 2>/dev/null | grep -qi "nvidia"; then
        if docker run --rm --gpus all "$IMAGE" nvidia-smi &>/dev/null 2>&1; then
            check_pass "Docker GPU 验证通过"
        else
            check_fail "Docker GPU 验证失败（镜像内 nvidia-smi 不可用）"
            echo "     请检查 Docker 镜像是否基于 CUDA 基础镜像"
        fi
    else
        check_fail "Docker 未注册 nvidia 运行时"
        echo "     请执行: sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker"
    fi
else
    check_pass "CPU 模式（未检测到 GPU 硬件，不影响使用）"
fi

# ── 3. Qlib 数据 ────────────────────────────────────────────
echo ""
echo "3️⃣  Qlib 数据"
QLIB_DATA="$QLIB_DATA_DIR"
if [ -d "$QLIB_DATA" ] && [ -d "$QLIB_DATA/features" ]; then
    file_count=$(find "$QLIB_DATA/features" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)
    check_pass "Qlib 数据: $QLIB_DATA (${file_count} 支股票)"
else
    check_fail "Qlib 数据不存在或不完整: $QLIB_DATA"
    echo "     🔧 从社区源下载 Qlib CN 数据 ..."
    echo "     来源: github.com/chenditc/investment_data"
    mkdir -p "$QLIB_DATA"
    DOWNLOADED=false
    URL="https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz"
    DOWNLOAD_DIR="${QLIB_DOWNLOAD_DIR:-$PROJECT_ROOT/qlib/downloads}"
    mkdir -p "$DOWNLOAD_DIR"
    TARBALL="$DOWNLOAD_DIR/qlib_bin.tar.gz"

    # 下载（带进度条；若缓存已存在则跳过）
    if [ -f "$TARBALL" ]; then
        CACHED_SIZE=$(stat -c%s "$TARBALL" 2>/dev/null || stat -f%z "$TARBALL" 2>/dev/null || echo "0")
        if [ "$CACHED_SIZE" -gt 1000000 ]; then
            echo "     ♻️  发现缓存: $TARBALL ($(du -h "$TARBALL" | cut -f1))，跳过下载"
        else
            echo "     ⚠️  缓存文件过小，重新下载..."
            rm -f "$TARBALL"
        fi
    fi

    if [ ! -f "$TARBALL" ]; then
        if command -v wget &>/dev/null; then
            echo "     正在下载 (wget) ..."
            wget --progress=bar:force -O "$TARBALL" "$URL" 2>&1
        elif command -v curl &>/dev/null; then
            echo "     正在下载 (curl) ..."
            curl -L --progress-bar -o "$TARBALL" "$URL" 2>&1
        else
            echo "     ❌ 未找到 wget 或 curl，无法下载"
        fi
    fi

    # 解压
    if [ -f "$TARBALL" ]; then
        FSIZE=$(stat -c%s "$TARBALL" 2>/dev/null || stat -f%z "$TARBALL" 2>/dev/null || echo "0")
        if [ "$FSIZE" -gt 1000000 ]; then
            echo "     正在解压 ..."
            TMP_EXTRACT="$DOWNLOAD_DIR/qlib_extract_$$"
            mkdir -p "$TMP_EXTRACT"
            tar -zxf "$TARBALL" -C "$TMP_EXTRACT"
            QLIB_BIN="$TMP_EXTRACT/qlib_bin"
            if [ -d "$QLIB_BIN/features" ]; then
                echo "     正在整理目录结构 ..."
                mv "$QLIB_BIN/features"    "$QLIB_DATA/features"
                mv "$QLIB_BIN/calendars"   "$QLIB_DATA/calendars"
                mv "$QLIB_BIN/instruments" "$QLIB_DATA/instruments"
                DOWNLOADED=true
            else
                mv "$QLIB_BIN"/* "$QLIB_DATA/" 2>/dev/null && DOWNLOADED=true
            fi
            rm -rf "$TMP_EXTRACT"
            echo "     💾 tar 包已保留在: $TARBALL (下次重置可直接复用)"
        else
            echo "     ❌ 下载文件过小 (${FSIZE} bytes)，可能下载失败"
            rm -f "$TARBALL"
        fi
    fi

    if $DOWNLOADED && [ -d "$QLIB_DATA" ] && [ "$(ls -A "$QLIB_DATA" 2>/dev/null | head -1)" ]; then
        check_fixed "Qlib 数据下载完成"
    else
        echo "     ❌ 自动下载失败，请手动:"
        echo "        wget -O $TARBALL https://github.com/chenditc/investment_data/releases/latest/download/qlib_bin.tar.gz"
        echo "        mkdir -p $QLIB_DATA && tar -zxf $TARBALL -C $QLIB_DATA --strip-components=1"
    fi
fi

# ── 4. Python 环境（智能发现最佳环境）─────────────────────────
echo ""
echo "4️⃣  本地 Python 环境 (用于模型快速验证)"

PYTHON_CMD=""
PYTHON_SOURCE=""

# 模型优化需要 PyTorch — 额外检查 torch
REQUIRED_MODULES="import pandas; import tables; import numpy; import torch"

# 方法1: 动态扫描所有 conda 环境
if command -v conda &>/dev/null; then
    while IFS= read -r env_path; do
        [ -z "$env_path" ] && continue
        candidate="$env_path/bin/python"
        [ ! -x "$candidate" ] 2>/dev/null && continue
        if $candidate -c "$REQUIRED_MODULES" &>/dev/null; then
            PYTHON_CMD="$candidate"
            PYTHON_SOURCE="conda:$(basename "$env_path")"
            break
        fi
    done < <(conda env list 2>/dev/null | grep -v "^#" | grep -v "^$" | awk '{print $NF}')
fi

# 方法2: fallback 到 PATH 中的 python/python3
if [ -z "$PYTHON_CMD" ]; then
    for candidate_info in \
        "$(command -v python 2>/dev/null)|python" \
        "$(command -v python3 2>/dev/null)|python3"; do
        cpath="${candidate_info%%|*}"
        csrc="${candidate_info##*|}"
        [ -z "$cpath" ] && continue
        [ ! -x "$cpath" ] 2>/dev/null && continue
        if $cpath -c "$REQUIRED_MODULES" &>/dev/null; then
            PYTHON_CMD="$cpath"
            PYTHON_SOURCE="$csrc"
            break
        fi
    done
fi

if [ -n "$PYTHON_CMD" ]; then
    PV=$($PYTHON_CMD --version 2>&1)
    check_pass "Python: $PV ($PYTHON_SOURCE → $PYTHON_CMD)"
    check_pass "pandas:  $($PYTHON_CMD -c 'import pandas; print(pandas.__version__)')"
    check_pass "tables:  $($PYTHON_CMD -c 'import tables; print(tables.__version__)')"
    check_pass "numpy:   $($PYTHON_CMD -c 'import numpy; print(numpy.__version__)')"
    check_pass "torch:   $($PYTHON_CMD -c 'import torch; print(torch.__version__)')"

    # pyarrow 可选但推荐
    if $PYTHON_CMD -c "import pyarrow" &>/dev/null; then
        check_pass "pyarrow: $($PYTHON_CMD -c 'import pyarrow; print(pyarrow.__version__)')"
    else
        check_warn "pyarrow 未安装 (加载 SOTA 因子需要)"
        echo "     🔧 安装 pyarrow ..."
        $PYTHON_CMD -m pip install pyarrow -q 2>&1 | tail -2
        if $PYTHON_CMD -c "import pyarrow" &>/dev/null; then
            check_fixed "pyarrow 已安装"
        fi
    fi
else
    check_fail "未找到有 pandas+tables+numpy+torch 的 Python"

    # 尝试自动修复
    FIX_PYTHON=""
    for p in \
        "$(command -v python 2>/dev/null)" \
        "$(command -v python3 2>/dev/null)"; do
        [ -n "$p" ] && [ -x "$p" ] 2>/dev/null && { FIX_PYTHON="$p"; break; }
    done

    if [ -n "$FIX_PYTHON" ]; then
        echo "     🔧 向 $FIX_PYTHON 安装 pandas tables numpy pyarrow torch ..."
        $FIX_PYTHON -m pip install pandas tables numpy pyarrow torch -q 2>&1 | tail -3
        if $FIX_PYTHON -c "$REQUIRED_MODULES" &>/dev/null; then
            check_fixed "依赖已安装 ($FIX_PYTHON)"
            PYTHON_CMD="$FIX_PYTHON"
        else
            echo "     ❌ 安装失败"
            echo "     建议: pip install pandas tables numpy pyarrow torch"
            echo "     或用 conda: conda create -n model_dev python=3.10 pandas tables numpy pyarrow pytorch -c pytorch -y"
        fi
    else
        echo "     ❌ 未找到任何 Python，请先安装 Python 3.8+"
        echo "     建议: conda create -n model_dev python=3.10 pandas tables numpy pyarrow pytorch -c pytorch -y"
    fi
fi

# 输出推荐 Python
if [ -n "$PYTHON_CMD" ]; then
    echo ""
    echo "  📋 推荐 Python: $PYTHON_CMD"
    if [[ "${PYTHON_SOURCE:-}" == conda:* ]]; then
        ENV_NAME="${PYTHON_SOURCE#conda:}"
        echo "     或: conda activate $ENV_NAME && python ..."
    fi
fi

# ── 5. conda 环境信息 ───────────────────────────────────────
echo ""
echo "5️⃣  conda 环境 (信息)"
if command -v conda &>/dev/null; then
    ACTIVE_ENV="${CONDA_DEFAULT_ENV:-未激活}"
    check_pass "conda 可用, 当前: $ACTIVE_ENV"
    echo "  📋 可用环境:"
    conda env list 2>/dev/null | grep -v "^#" | grep -v "^$" | sed 's/^/     /'
else
    check_warn "conda 未检测到 (不影响核心功能)"
fi

# ── 汇总 ────────────────────────────────────────────────────
echo ""
echo "============================================"
SUMMARY="✅ $PASS 通过"
[ "$FIXED" -gt 0 ] && SUMMARY="$SUMMARY  🔧 $FIXED 已修复"
[ "$FAIL" -gt 0 ] && SUMMARY="$SUMMARY  ❌ $FAIL 失败"
[ "$WARN" -gt 0 ] && SUMMARY="$SUMMARY  ⚠️  $WARN 警告"
echo "  📊 $SUMMARY"
echo "============================================"

ACTUAL_FAIL=$((FAIL - FIXED))
if [ "$ACTUAL_FAIL" -gt 0 ]; then
    echo ""
    echo "❌ 仍有 $ACTUAL_FAIL 项未解决，请手动处理后重新运行。"
    exit 1
else
    echo ""
    echo "🎉 环境就绪！可以开始模型优化了。"
    [ -n "$PYTHON_CMD" ] && echo "💡 模型验证用: $PYTHON_CMD"
    exit 0
fi
