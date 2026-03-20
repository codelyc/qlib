# Docker 回测命令参考

## 前提

- Docker 镜像 `local_qlib:latest` 已构建
- Qlib 数据已下载到 `$PROJECT_ROOT/data/qlib/cn_data/`（通过 `setup_env.sh` 自动下载）

## 构建 Docker 镜像

```bash
# 在项目根目录下执行
docker build -t local_qlib:latest -f rdagent/scenarios/qlib/docker/Dockerfile rdagent/scenarios/qlib/docker/
```

## 运行因子计算

```bash
# 单个因子计算
docker run --rm \
  -v /absolute/path/to/factor_dir:/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && python factor.py"
```

## 运行 Qlib 回测

```bash
# 基线回测（只用 Alpha158）
docker run --rm \
  -v /absolute/path/to/workspace:/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && qrun conf_baseline.yaml"

# 合并因子回测（Alpha158 + 自定义因子）
docker run --rm \
  -v /absolute/path/to/workspace:/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && qrun conf_combined_factors.yaml"
```

## 提取回测结果

```bash
docker run --rm \
  -v /absolute/path/to/workspace:/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && python read_exp_res.py"
```

## 查看回测结果

回测完成后，工作空间中会生成：
- `qlib_res.csv` — 回测指标（IC, ICIR, 年化收益, 夏普等）
- `ret.pkl` — 收益曲线数据（可用 pandas 加载绘图）
- `mlruns/` — MLflow 完整记录

## GPU 支持

如需 GPU（深度学习模型时）：
```bash
docker run --rm --gpus all \
  -v /absolute/path/to/workspace:/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data \
  --shm-size=16g \
  local_qlib:latest \
  bash -c "cd /workspace/qlib_workspace && qrun conf_combined_factors.yaml"
```

## 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `docker: Error response from daemon` | Docker 未启动 | `sudo systemctl start docker` |
| `No such image: local_qlib:latest` | 未构建镜像 | 执行构建命令 |
| `FileNotFoundError: daily_pv.h5` | 因子代码中数据文件不存在 | 因子代码在 Docker 中通过 Qlib API 读取数据 |
| `qrun: command not found` | Qlib 未安装 | 镜像构建时已包含 |
| 回测超时 | 数据量大 / 模型复杂 | 增加 `--timeout` 或简化因子 |

## 数据文件说明

Docker 中因子代码可以通过两种方式获取数据：

**方式 A（推荐）：读取预生成的 daily_pv.h5**
```python
df = pd.read_hdf("daily_pv.h5", key="data")
```
> 注意：需要先在 Docker 中生成此文件（见下方脚本）

**方式 B：直接用 Qlib API**
```python
import qlib
from qlib.data import D
qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")
instruments = D.instruments("csi300")
data = D.features(instruments, ["$open", "$close", "$high", "$low", "$volume", "$vwap"], freq="day")
```

**生成 daily_pv.h5 的脚本**（放在工作空间中运行一次）：
```python
import qlib
from qlib.data import D
import pandas as pd

qlib.init(provider_uri="~/.qlib/qlib_data/cn_data")
instruments = D.instruments("csi300")
data = D.features(
    instruments,
    ["$open", "$close", "$high", "$low", "$volume", "$vwap", "$factor"],
    freq="day",
    start_time="2005-01-01"
)
data.to_hdf("daily_pv.h5", key="data")
print(f"Saved daily_pv.h5: {data.shape}")
```
