---
name: fin-factor
description: 'Qlib 因子自动研发 Agent。理解用户想法、设计因子方案、编写代码、Docker+Qlib 回测、分析结果、循环优化。Use when: 挖因子、写因子、因子研发、Alpha 因子、因子回测、fin factor、量化因子。'
argument-hint: '说出你的想法就行，比如"我觉得大跌后放量反弹的股票后面会涨"、"最近换手率异常的股票表现怎样"'
---

# Qlib 因子自动研发 Agent

## 概述

用户用自然语言描述想法，Agent 负责：
1. **理解想法** — 有疑问就追问
2. **给方案** — 展示因子设计（人话+算法+例子），用户确认后才执行
3. **写代码** — 实现因子计算
4. **快速验证** — debug 数据 <30秒验证代码正确性
5. **Docker 回测** — 全量数据验证因子是否有效
6. **分析反馈** — 汇报结果，建议下一步

**核心原则**：用户不需要懂量化术语；**先验证后回测**；每轮都询问用户。

---

## 前置条件

**⚠️ 开始因子研发前，必须先让用户执行环境初始化脚本：**

```bash
bash .github/skills/fin-factor/scripts/setup_env.sh
```

交互式流程：
1. 询问是否重置环境（默认 N，回车跳过；输入 y 则删除 Docker 镜像 + Qlib 数据）
2. 自动检查：Docker、镜像、Qlib 数据、Python 依赖
3. 缺什么自动装什么（构建镜像、下载数据、pip install）

**所有检查通过后才开始工作。**

---

## 脚本清单

脚本位于 [./scripts/](./scripts/)，初始化时复制到工作空间。

| 脚本 | 作用 | 运行环境 |
|------|------|---------|
| [setup_env.sh](./scripts/setup_env.sh) | 环境初始化/检查/修复（交互式） | 本地 bash |
| [init_workspace.sh](./scripts/init_workspace.sh) | 一键初始化（创建目录+生成数据+复制模板+动态日期替换） | 本地 bash |
| [gen_daily_pv.py](./scripts/gen_daily_pv.py) | 生成 full + debug 数据 + data_end_date.txt | Docker |
| [validate_factor.py](./scripts/validate_factor.py) | debug 数据快速验证因子代码 | 本地 Python |
| [merge_factors.py](./scripts/merge_factors.py) | 合并因子 + 格式验证 + IC 去重 | 本地 Python |
| [run_backtest.sh](./scripts/run_backtest.sh) | Docker 回测（带重试） | bash→Docker |
| [analyze_results.py](./scripts/analyze_results.py) | 解析指标 + 对比 SOTA → JSON | 本地 Python |
| [update_sota.py](./scripts/update_sota.py) | 更新 SOTA 记录 | 本地 Python |

---

## 完整工作流程

### 第 0 步：初始化工作空间

```bash
bash .github/skills/fin-factor/scripts/init_workspace.sh [可选名称]
```

脚本最后一行输出 `EXP_ROOT=<绝对路径>`。**Agent 必须记住这个路径**，后续所有步骤都用它。路径格式为 `<项目根>/factor_workspace/<名称>`。

初始化后的 `$EXP_ROOT/` 包含：数据文件（`daily_pv.h5` + `daily_pv_debug.h5`）、所有脚本、回测配置模板、`sota_record.json`。

### 第 1 步：理解用户想法 & 确认方案

#### 首轮引导

> 你可以随便说一个想法，比如：
> - "大跌之后放量反弹的股票后面会涨"
> - "最近波动特别大的股票是不是风险更高"
> - 或者任何直觉 / 观察 / 论文思路

#### 理解 & 追问

1. 用自己的话复述理解
2. 追问关键模糊点（最多 1-2 个）

#### 展示方案（执行前必须确认）

> 🎯 **我理解你的想法是**：...
>
> 📋 **我打算做以下因子**：
>
> | 因子 | 用人话说 | 具体算法 |
> |------|---------|----------|
> | xxx | ... | ... |
>
> 📌 **举个例子**：假设某只股票昨天跌了4%，今天涨了1.2%...
>
> ✅ 这样做可以吗？

**确认后才写代码。**

#### 后续轮次

先汇报上轮结果（第 6 步），再询问：深入挖 / 换方向 / 微调 / 停止。

### 第 2 步：编写因子代码

```bash
ROUND=1
ROUND_DIR="$EXP_ROOT/round_$ROUND"
mkdir -p "$ROUND_DIR/{因子名}"
```

每个因子写一个 `$ROUND_DIR/{因子名}/factor.py`。

代码规范和模板见 [factor-code-spec.md](./references/factor-code-spec.md)。
更多示例见 [factor-examples.md](./references/factor-examples.md)。

### 第 3 步：快速验证（debug 数据，<30秒）

```bash
# ⚠️ 使用 cp 而非 ln -sf（Docker 无法跟随宿主机符号链接）
cp "$EXP_ROOT/daily_pv_debug.h5" "$ROUND_DIR/{因子名}/daily_pv.h5"
python "$EXP_ROOT/validate_factor.py" "$ROUND_DIR/{因子名}"
```

验证项：代码能否执行、result.h5 格式、MultiIndex、float64、NaN 比例、日级数据。

**注意**：`validate_factor.py` 在**本地 Python 环境**执行，需要 `pandas` + `tables`。如果报 `ModuleNotFoundError`，请先 `conda activate <环境名>` 或 `pip install pandas tables`。

**失败 → 修改代码 → 重新验证。通过后才进第 4 步。**

### 第 4 步：全量计算 + 合并 + 回测

#### 4.1 Docker 全量执行

```bash
# ⚠️ 使用 cp 而非 ln -sf（Docker 挂载后符号链接指向容器外路径，会 FileNotFoundError）
cp "$EXP_ROOT/daily_pv.h5" "$ROUND_DIR/{因子名}/daily_pv.h5"
docker run --rm \
  -v "$ROUND_DIR/{因子名}":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data --shm-size=16g \
  local_qlib:latest bash -c "cd /workspace/qlib_workspace && python factor.py"
```

对每个因子都执行。

> 📌 **为什么不用符号链接？** Docker `-v` 挂载目录后，容器内看到的符号链接目标路径是宿主机绝对路径，在容器内不存在。直接复制文件虽然占磁盘，但可靠。

#### 4.2 合并因子（验证 + IC 去重）

```bash
python "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
  --sota-file "$EXP_ROOT/sota_combined.parquet"
```

产出：`$ROUND_DIR/combined_factors_df.parquet`

#### 4.3 一键回测

```bash
cp "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/"
bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR"
```

回测内部：Alpha158 + 你的新因子 → LightGBM → Top50 选股 → 回测。失败自动重试 3 次。

产出：`qlib_res.csv`、`ret.pkl`

### 第 5 步：分析结果 + 更新 SOTA

```bash
python "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
  --sota-file "$EXP_ROOT/sota_record.json"
python "$EXP_ROOT/update_sota.py" "$EXP_ROOT" "$ROUND_DIR" $ROUND
```

产出：`$ROUND_DIR/analysis.json`（指标对比 + 是否更新 SOTA）

### 第 6 步：生成报告 + 向用户汇报

1. **写入** `$ROUND_DIR/report.md` — 模板见 [report-templates.md](./references/report-templates.md)
2. **追加** `$EXP_ROOT/summary.md` — 模板见 [report-templates.md](./references/report-templates.md)
3. **在对话中展示**：
   - 本轮策略（用人话）+ 关键指标对比表
   - 成功/失败原因
   - 文件位置
   - 下一轮建议 + 询问用户

---

## 单轮速查

```bash
ROUND=1; ROUND_DIR="$EXP_ROOT/round_$ROUND"
# 创建目录
mkdir -p "$ROUND_DIR/{factor_name}"
# 写 factor.py（Agent 完成）
# 快速验证（⚠️ 用 cp 不用 ln -sf）
cp "$EXP_ROOT/daily_pv_debug.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
python "$EXP_ROOT/validate_factor.py" "$ROUND_DIR/{factor_name}"
# 全量执行（⚠️ 用 cp 不用 ln -sf）
cp "$EXP_ROOT/daily_pv.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
docker run --rm -v "$ROUND_DIR/{factor_name}":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/data/qlib":/root/.qlib/qlib_data --shm-size=16g \
  local_qlib:latest bash -c "cd /workspace/qlib_workspace && python factor.py"
# 合并 + 回测
python "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" --sota-file "$EXP_ROOT/sota_combined.parquet"
cp "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/"
bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR"
# 分析 + SOTA
python "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" --sota-file "$EXP_ROOT/sota_record.json"
python "$EXP_ROOT/update_sota.py" "$EXP_ROOT" "$ROUND_DIR" $ROUND
```

---

## 数据流转

```
用户想法 → Agent 理解确认
  → factor.py → validate (debug, <30s)
  → 通过? 否→修改 / 是→Docker全量执行
  → result.h5 → merge (验证+去重)
  → parquet → run_backtest (qrun+重试)
  → qlib_res.csv → analyze (对比SOTA)
  → update_sota → report → 汇报用户 → 下一轮
```

---

## 回测配置

| 参数 | 默认值 |
|------|--------|
| 股票池 | CSI300 |
| 训练期 | 2008-01-01 ~ 2014-12-31 |
| 验证期 | 2015-01-01 ~ 2016-12-31 |
| 测试期 | 2017-01-01 ~ 最新 |
| 模型 | LightGBM |
| 持仓 | Top50，每天换 5 只 |
| 交易成本 | 买入万五 / 卖出万十五 |

---

## 经验指导

- **前 5 轮**：简单因子（动量、反转、量价比）
- **5-15 轮**：多窗口期、非线性变换
- **15+ 轮**：ML 因子（PCA残差、Autoencoder）
- **陷阱**：时间泄露、过拟合、因子共线性（IC>0.99）

---

## 已知问题 & 注意事项

| 问题 | 说明 | 解决方案 |
|------|------|----------|
| Docker 符号链接 | Docker `-v` 挂载后容器内符号链接指向宿主机路径，不可用 | 用 `cp` 代替 `ln -sf` |
| Docker 文件权限 | 容器以 root 创建的文件（mlruns/）宿主机普通用户无法删除 | `run_backtest.sh` 自动用 Docker 清理旧产出 |
| YAML 日期 | 回测 end_time 不能是数据最后一天（Qlib 日历边界越界） | `init_workspace.sh` 自动从 `data_end_date.txt` 读取安全日期 |
| 本地 Python 依赖 | `validate_factor.py` / `merge_factors.py` 需要 pandas+tables | 开始前运行 `setup_env.sh` 确认 |
