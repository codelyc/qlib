---
name: fin-factor
description: 'Qlib 因子自动研发 Agent。理解用户想法、设计因子方案、编写代码、Docker+Qlib 回测、分析结果、循环优化。Use when: 挖因子、写因子、因子研发、Alpha 因子、因子回测、fin factor、量化因子。'
argument-hint: '描述选股直觉即可，例如："大跌后放量反弹会涨"'
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
bash .github/skills/fin-factor/scripts/main_setup.sh
```

交互式流程：
1. 询问是否重置环境（默认 N，回车跳过；输入 y 则删除 Docker 镜像 + Qlib 数据）
2. 自动检查：Docker、镜像、Qlib 数据、Python 依赖
3. 缺什么自动装什么（构建镜像、下载数据、pip install）

**所有检查通过后才开始工作。**

### `.env` 环境配置

项目根目录的 `.env` 文件是所有脚本的**唯一配置中心**，已被加入 `.gitignore` 不会提交 git。

```bash
# 首次使用：从模板复制并填写本机路径
cp .env.template .env
```

**变量命名规则**：
- 基础设施变量用**大写**：`PROJECT_ROOT`, `DOCKER_IMAGE`, `QLIB_DATA_DIR` 等
- 回测参数用**小写**：`train_start`, `topk`, `learning_rate` 等（与 YAML 模板 `{{ 变量名 }}` 一一对应）

**工作原理**：脚本 `source .env` 后，所有变量自动导出为环境变量。`qrun` 原生从 `os.environ` 读取这些变量填充 Jinja2 模板。如果变量未设置，YAML 模板中的 `default()` 值会兜底。

临时覆盖：`export topk=30 && qrun conf_combined_factors.yaml`

> ⚠️ 找不到 `.env` 时脚本会报错并列出所有必需变量，按提示填写即可。

---

## 脚本清单

脚本位于 [./scripts/](./scripts/)，初始化时复制到工作空间。

| 脚本 | 作用 | 运行环境 |
|------|------|---------|
| [main_setup.sh](./scripts/main_setup.sh) | 环境初始化/检查/修复（交互式） | 本地 bash |
| [init_workspace.sh](./scripts/init_workspace.sh) | 一键初始化（创建目录+生成数据+复制模板+动态日期替换） | 本地 bash |
| [gen_daily_pv.py](./scripts/gen_daily_pv.py) | 生成 full + debug 数据 + data_end_date.txt | Docker |
| [validate_factor.py](./scripts/validate_factor.py) | debug 数据快速验证因子代码 | 本地 Python |
| [merge_factors.py](./scripts/merge_factors.py) | 合并因子 + 格式验证 + IC 去重（支持 `--single` 单因子模式） | 本地 Python |
| [run_backtest.sh](./scripts/run_backtest.sh) | 合并因子 Docker 回测（带重试） | bash→Docker |
| [run_single_backtest.sh](./scripts/run_single_backtest.sh) | 单因子独立 Docker 回测（当前 `ACTIVE_FEATURE_SET` + 单因子） | bash→Docker |
| [run_round.sh](./scripts/run_round.sh) | **一键编排**：单因子回测 → 合并回测 → 分析 | bash→Docker |
| [analyze_results.py](./scripts/analyze_results.py) | 解析指标 + 对比 SOTA → JSON（支持 `--factor-dir` 单因子分析） | 本地 Python |
| [update_sota.py](./scripts/update_sota.py) | 更新 SOTA 记录 | 本地 Python |
| [collect_error.py](./scripts/collect_error.py) | 记录/标注/汇总错误知识库（对应 `error_knowledge.jsonl`） | 本地 Python |
| [run_baseline.sh](./scripts/run_baseline.sh) | 基线回测（当前 `ACTIVE_FEATURE_SET` + 默认模型）→ `baseline_record.json` | bash→Docker |

---

## 完整工作流程

### 第 0 步：初始化工作空间

```bash
bash .github/skills/fin-factor/scripts/init_workspace.sh [可选名称]
```

脚本最后一行输出 `EXP_ROOT=<绝对路径>`。**Agent 必须记住这个路径**，后续所有步骤都用它。路径格式为 `<项目根>/factor_workspace/<名称>`。

初始化后的 `$EXP_ROOT/` 包含：数据文件（`daily_pv.h5` + `daily_pv_debug.h5`）、所有脚本、回测配置模板、`sota_record.json`（动态基线）、`baseline_record.json`（静态基线，由 `run_baseline.sh` 自动生成）。

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

Agent 必须先形成结构化假设（格式见 [hypothesis-feedback.md](./references/hypothesis-feedback.md)），再展示给用户：

> 🎯 **我理解你的想法是**：...
>
> 💡 **假设**：[可验证的陈述，说明为什么预期有效]
>
> 📋 **我打算做以下因子**（每轮 1-5 个）：
>
> | 因子 | 用人话说 | 具体算法 | 数学公式 |
> |------|---------|----------|----------|
> | xxx | ... | ... | $\text{formula}$ |
>
> 📌 **举个例子**：假设某只股票昨天跌了4%，今天涨了1.2%...
>
> ✅ 这样做可以吗？

**确认后才写代码。**

#### 后续轮次

先汇报上轮结果（第 6 步，使用 [hypothesis-feedback.md](./references/hypothesis-feedback.md) 中的反馈模板），再询问：深入挖 / 换方向 / 微调 / 停止。

### 第 1.5 步：因子规范设计 (Specification)

在确认想法后、写代码前，你必须遵循 RD-Agent 的规范哲学（见 [rd-agent-specs.md](./references/rd-agent-specs.md)），**先输出一份纯 Markdown 的接口规范**。

- 因子实验输出格式，请严格遵守 [rd-agent-specs.md](./references/rd-agent-specs.md) 中的 `因子实验输出格式`（含 description, formulation, variables）。
- 因子特征计算逻辑规范，请参考 [rd-agent-specs.md](./references/rd-agent-specs.md) 中的 `特征工程规范`。
- 数据输入约束请参考 [rd-agent-specs.md](./references/rd-agent-specs.md) 中的 `数据加载规范`。

> 🎯 **因子 Specification 示例**
>
> ```json
> {
>     "drop_rebound_factor": {
>         "description": "[量价反转因子] 大跌后放量反弹信号，衡量跌幅与反弹量的交互强度",
>         "formulation": "F = \\frac{Volume_t}{MA(Volume, 20)} \\times |R_{t-1}| \\times \\mathbb{1}(R_{t-1} < -0.03 \\wedge R_t > 0)",
>         "variables": {
>             "Volume_t": "当日成交量",
>             "MA(Volume, 20)": "20日成交量均值",
>             "R_t": "当日收益率 = Close_t / Close_{t-1} - 1",
>             "R_{t-1}": "前一日收益率（shift(1)回看，无未来泄露）"
>         }
>     }
> }
> ```
>
> - **输入**: `$close`, `$volume`（从 daily_pv.h5 读取）
> - **输出**: float64 DataFrame，MultiIndex=(datetime, instrument)，单列
> - **约束**: 无前向偏误（所有 shift > 0），分母加 1e-8，不使用 dropna()

**确认 Specification 无误后才允许写实现代码。**

### 第 1.6 步：读取历史错误经验（每轮必做）

**并行与第 1.5 步，设计规范的同时运行：**

```bash
# 读取历史错误知识库摘要（借鉴 RD-Agent error_summary 注入提示词的思路）
$PYTHON_BIN "$EXP_ROOT/collect_error.py" summary \
    --exp-root "$EXP_ROOT" --round $ROUND
```

**Agent 必须对照输出做两件事：**
1. **未修复错误** → 将错误类型和原因内化到本轮代码设计中，主动避坑
2. **已修复经验** → 在 `factor.py` 中加入防御性写法

> ⚠️ **如果知识库为空**（首轮）输出 `暂无历史错误`，可忽略。

### 第 1.7 步：挑战提炼（第 2 轮起必做）

> ⚠️ **首轮跳过此步骤**（无实验历史）。

对标 RD-Agent prompts_v2 的 `feedback_problem` / `scenario_problem` 机制，从实验历史中系统性提炼挑战，确保后续假设"有的放矢"。

**操作步骤**：

1. 读取 `$EXP_ROOT/summary.md` — 提取所有轮次的假设、指标、决策
2. 读取 `$EXP_ROOT/error_knowledge.jsonl` — 提取失败模式
3. 读取上一轮的 `analysis.json` — 提取最新指标对比
4. 对照挑战分类表（见 [challenge-extraction.md](./references/challenge-extraction.md)）逐条检查
5. 输出 `$ROUND_DIR/challenges.json`

**挑战分两类**：
- **Dataset-Driven**：高 NaN 率、因子共线性、覆盖率不足、窗口期不匹配
- **Domain-Informed**：时间泄露、换手过高、因子衰退、市值偏差、行业集中

**后续假设必须引用挑战 ID**（如 "针对 ch_001"）。如果忽略 high-severity 挑战，必须说明理由。

> 📖 完整分类体系、输出格式和示例见 [challenge-extraction.md](./references/challenge-extraction.md)

### 第 1.8 步：不确定项咨询用户

在第 1.5-1.7 步完成后、写代码前，Agent 必须识别当前轮次是否存在不确定因素，如有则**主动向用户提出 1-2 个可选择的问题**。

**典型场景**：

| 场景 | 问题示例 |
|------|---------|
| **用户目标不明** | "你更看重收益率还是控制回撤？" |
| **多个可行方案** | "波动率因子有 std 和 mad 两种思路，你更倾向哪种？" |
| **指标冲突** | "上轮收益提升但回撤也变大了，你接受这个权衡吗？" |
| **SOTA 接近持平** | "这轮成绩和 SOTA 几乎一样，你要更新还是保守不动？" |

**规则**：
- 每轮最多问 **1-2 个**高价值问题，不能变成问卷调查
- 问题必须**可选择**（给出 2-3 个选项），不提开放式空泛问题
- 如果用户未及时回复，按**默认策略**执行，并在报告中标注"⚠️ 使用默认策略"

> 💡 **默认策略**：收益优先、简单因子优先、SOTA 按年化收益判断。

### 第 2 步：编写因子代码

```bash
ROUND=1
ROUND_DIR="$EXP_ROOT/round_$ROUND"
mkdir -p "$ROUND_DIR/{因子名}"
```

每个因子写一个 `$ROUND_DIR/{因子名}/factor.py`。

代码规范和模板见 [factor-code-spec.md](./references/factor-code-spec.md)。
同时必须遵守 [rd-agent-specs.md](./references/rd-agent-specs.md) 中的 `Qlib Invocation Specification`，确保产出的数据严格符合 Qlib 的格式要求。
更多示例见 [factor-examples.md](./references/factor-examples.md)。

**开始编写前，Agent 必须对照第 1.6 步输出的历史错误检查代码，并严格遵守第 1.5 步设计的 Specification。**

### 第 3 步：快速验证（debug 数据，<30秒）

```bash
# ⚠️ 使用 cp 而非 ln -sf（Docker 无法跟随宿主机符号链接）
cp "$EXP_ROOT/daily_pv_debug.h5" "$ROUND_DIR/{因子名}/daily_pv.h5"
$PYTHON_BIN "$EXP_ROOT/validate_factor.py" "$ROUND_DIR/{因子名}"
```

验证项：代码能否执行、result.h5 格式、MultiIndex、float64、NaN 比例、日级数据。

**注意**：`validate_factor.py` 在**本地 Python 环境**执行，需要 `pandas` + `tables`。如果报 `ModuleNotFoundError`，请先 `conda activate <环境名>` 或 `pip install pandas tables`。

**失败 → 修改代码 → 重新验证。通过后才进第 4 步。**

### 第 4 步：全量计算 + 单因子回测 + 合并回测

#### 4.1 Docker 全量执行

```bash
# ⚠️ 使用 cp 而非 ln -sf（Docker 挂载后符号链接指向容器外路径，会 FileNotFoundError）
cp "$EXP_ROOT/daily_pv.h5" "$ROUND_DIR/{因子名}/daily_pv.h5"
docker run --rm \
  -v "$ROUND_DIR/{因子名}":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/qlib/data":/qlib_data --shm-size=16g \
  local_qlib:latest bash -c "cd /workspace/qlib_workspace && python factor.py"
```

对每个因子都执行。

> 📌 **数据路径说明**：数据放在 `qlib/data/` 下（含 `features/`、`calendars/`、`instruments/` 子目录），Docker 挂载到容器内 `/qlib_data`，`provider_uri` 使用绝对路径 `/qlib_data`。
> 📌 **为什么不用符号链接？** Docker `-v` 挂载目录后，容器内看到的符号链接目标路径是宿主机绝对路径，在容器内不存在。直接复制文件虽然占磁盘，但可靠。

#### 4.2 单因子独立回测（新增）

对每个因子做独立回测（当前 `ACTIVE_FEATURE_SET` + 单因子），观察每个因子的独立增量贡献。单因子回测仅作参考，不做筛选——所有因子都参与最终合并。

```bash
# 对每个因子执行：
# 1) 生成单因子 parquet
$PYTHON_BIN "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
  --single "{因子名}" --sota-file "$EXP_ROOT/sota_combined.parquet"
# 2) 单因子回测
bash "$EXP_ROOT/run_single_backtest.sh" "$ROUND_DIR" "{因子名}"
# 3) 分析单因子结果
$PYTHON_BIN "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
  --factor-dir "{因子名}" --sota-file "$EXP_ROOT/sota_record.json" \
  --baseline-file "$EXP_ROOT/baseline_record.json"
```

产出：`$ROUND_DIR/{因子名}/qlib_res.csv`、`$ROUND_DIR/{因子名}/analysis.json`

> 💡 **归因先于合并**：先知道每个因子的独立价值，合并后才能准确归因"总分变化是谁的贡献"。
> ⚠️ **时间开销**：每个因子约 5-10 分钟，3 个因子就是 15-30 分钟。

#### 4.3 合并因子（验证 + IC 去重）

```bash
$PYTHON_BIN "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" \
  --sota-file "$EXP_ROOT/sota_combined.parquet"
```

产出：`$ROUND_DIR/combined_factors_df.parquet`

#### 4.4 合并回测

```bash
cp "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/"
bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR"
```

回测内部：当前 `ACTIVE_FEATURE_SET` + 所有新因子 → LightGBM → Top50 选股 → 回测。失败自动重试 3 次。

产出：`qlib_res.csv`、`ret.pkl`

#### 4.5 一键执行（4.2 + 4.3 + 4.4）

以上步骤可用 `run_round.sh` 一键完成：

```bash
bash "$EXP_ROOT/run_round.sh" "$ROUND_DIR"
```

自动编排：扫描因子 → 逐个单因子回测 → 合并 → 合并回测 → 分析（含单因子汇总）

### 第 5 步：分析结果 + 更新 SOTA

```bash
$PYTHON_BIN "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" \
  --sota-file "$EXP_ROOT/sota_record.json" \
  --baseline-file "$EXP_ROOT/baseline_record.json"
$PYTHON_BIN "$EXP_ROOT/update_sota.py" "$EXP_ROOT" "$ROUND_DIR" $ROUND
```

产出：`$ROUND_DIR/analysis.json`（指标对比 + 是否更新 SOTA）

### 第 5.5 步：训练日志分析（回测后必做）

对标 RD-Agent 对 `experiment.stdout` 的分析要求。回测产出 `qlib_res.csv` 后、生成报告前，Agent **必须**分析训练日志：

```bash
# 日志位于回测 Docker 输出
cat "$ROUND_DIR/docker_run.log" | grep -E "early stopping|training's mse|valid's mse|feature importance"
```

**必查 4 项**（详见 [hypothesis-feedback.md](./references/hypothesis-feedback.md) §3.2）：
1. **Early Stopping** — 前期触发（< 30 轮）说明学习率过高
2. **Loss 趋势** — valid loss 上升 = 过拟合
3. **特征重要性** — 新因子是否进入前 10
4. **训练时间** — > 10 分钟需优化

分析结果写入反馈 JSON 的 `training_log_analysis` 字段。

### 第 6 步：生成报告 + 向用户汇报

1. **生成结构化反馈** — 格式见 [hypothesis-feedback.md](./references/hypothesis-feedback.md) 中的 `反馈分析`（含因子执行状态、训练日志分析、增量归因）
2. **写入** `$ROUND_DIR/report.md` — 模板见 [report-templates.md](./references/report-templates.md)
3. **追加** `$EXP_ROOT/summary.md` — 模板见 [report-templates.md](./references/report-templates.md)
4. **在对话中展示**（使用 [hypothesis-feedback.md](./references/hypothesis-feedback.md) 中的反馈展示模板）：
   - 假设验证结论（✅成立 / ❌不成立 / ⚠️部分成立 / ❓无法验证-因子全部失败）
   - 关键指标**三列对比表**（本轮 vs Baseline vs SOTA，见 §4.0 双基线体系）
   - **单因子独立回测汇总表**（每个因子的 IC、年化收益、夏普比率等独立指标）
   - 训练日志分析摘要（early stopping / 过拟合信号 / 特征重要性）
   - 增量归因摘要（哪个因子贡献最大——基于单因子回测数据）
   - 成功/失败原因分析
   - 下一步建议（基于 SOTA 决策树判断：深挖 / 换方向 / 微调 / 停止）

---

## 单轮速查

```bash
ROUND=1; ROUND_DIR="$EXP_ROOT/round_$ROUND"
# 创建目录
mkdir -p "$ROUND_DIR/{factor_name}"
# 写 factor.py（Agent 完成）

# --- 快速验证（⚠️ 用 cp 不用 ln -sf） ---
cp "$EXP_ROOT/daily_pv_debug.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
$PYTHON_BIN "$EXP_ROOT/validate_factor.py" "$ROUND_DIR/{factor_name}"

# --- 全量执行（⚠️ 用 cp 不用 ln -sf） ---
cp "$EXP_ROOT/daily_pv.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
docker run --rm -v "$ROUND_DIR/{factor_name}":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/qlib/data":/qlib_data --shm-size=16g \
  local_qlib:latest bash -c "cd /workspace/qlib_workspace && python factor.py"

# --- 4.2 单因子回测 + 4.3 合并 + 4.4 合并回测 + 5 分析（一键执行） ---
bash "$EXP_ROOT/run_round.sh" "$ROUND_DIR"

# --- 或者分步执行 ---
# 4.2 单因子回测（对每个因子）:
$PYTHON_BIN "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" --single "{factor_name}" --sota-file "$EXP_ROOT/sota_combined.parquet"
bash "$EXP_ROOT/run_single_backtest.sh" "$ROUND_DIR" "{factor_name}"
$PYTHON_BIN "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" --factor-dir "{factor_name}" --sota-file "$EXP_ROOT/sota_record.json" --baseline-file "$EXP_ROOT/baseline_record.json"

# 4.3 合并 + 4.4 合并回测:
$PYTHON_BIN "$EXP_ROOT/merge_factors.py" "$ROUND_DIR" --sota-file "$EXP_ROOT/sota_combined.parquet"
cp "$EXP_ROOT/conf_combined_factors.yaml" "$EXP_ROOT/read_exp_res.py" "$ROUND_DIR/"
bash "$EXP_ROOT/run_backtest.sh" "$ROUND_DIR"

# 5 分析（自动汇总单因子结果） + 5.5 训练日志:
$PYTHON_BIN "$EXP_ROOT/analyze_results.py" "$ROUND_DIR" --sota-file "$EXP_ROOT/sota_record.json" --baseline-file "$EXP_ROOT/baseline_record.json"
cat "$ROUND_DIR/docker_run.log" | grep -E "early stopping|training's mse|valid's mse|feature importance"
$PYTHON_BIN "$EXP_ROOT/update_sota.py" "$EXP_ROOT" "$ROUND_DIR" $ROUND
```

---

## 数据流转

```
用户想法 → Agent 理解确认
  → [第2轮起] 挑战提炼 (challenges.json)
  → 假设生成 → 5维打分 → Critique → Rewrite → 用户确认
  → [不确定?] 咨询用户 (1-2个选择题)
  → Agent 选参数（编辑 .env 或 export 临时覆盖）
  → factor.py → validate (debug, <30s)
  → 通过? 否→修改 / 是→Docker全量执行
  → result.h5
  → [阶段1] 单因子独立回测（逐个）
     merge --single → single_factor_df.parquet
     → run_single_backtest → qlib_res.csv (因子目录)
     → analyze --factor-dir → analysis.json (因子目录)
  → [阶段2] 合并回测
     merge → combined_factors_df.parquet
     → run_backtest → qlib_res.csv (轮次目录)
     → analyze (对比 Baseline + SOTA + 单因子汇总)
  → 训练日志分析 (docker_run.log)
  → 指标不满意? → Agent 调参数 → 重跑
  → 满意 → update_sota → report (含单因子对比表) → 汇报用户 → 下一轮
```

---

## 配置体系

所有回测参数统一在项目根目录的 **`.env`** 文件中配置。YAML 模板用 `{{ var }}` 引用，`qrun` 从 `os.environ` 自动读取。

**优先级**（高→低）：`export` 临时覆盖 > `.env` 中的值 > YAML 模板内 `default()` 兜底。

### 可配置参数一览

| 参数 | 默认值 | 含义 | Agent 何时调整 |
|------|--------|------|---------------|
| `provider_uri` | `/qlib_data` | Qlib 数据目录（Docker 内挂载点，对应 `-v $PROJECT_ROOT/qlib/data:/qlib_data`） | 切换数据源 |
| `market` | `csi300` | 股票池 | 换成 csi500 扩大选股范围 |
| `train_start` | `2020-01-01` | 训练期起始 | 根据实际数据起始日期调整 |
| `train_end` | `2022-12-31` | 训练期结束 | — |
| `valid_start` | `2023-01-01` | 验证期起始 | — |
| `valid_end` | `2024-12-31` | 验证期结束 | — |
| `test_start` | `2025-01-01` | 测试期起始 | — |
| `test_end` | `null` | 数据结束（null=自动取最后一天） | — |
| `topk` | `50` | 持仓股票数 | 因子区分度高→降到30；低→升到100 |
| `n_drop` | `5` | 每天最多换出数 | 换手率太高→增大 |
| `learning_rate` | `0.2` | 学习率 | 快速验证用0.2；精调用0.05 |
| `max_depth` | `8` | 树深度 | 过拟合→降到5 |
| `num_leaves` | `210` | 叶子数 | 过拟合→降到128 |
| `lambda_l1` | `205.6999` | L1 正则 | 过拟合→增大 |
| `lambda_l2` | `580.9768` | L2 正则 | 过拟合→增大 |
| `open_cost` | `0.0005` | 买入成本（万五） | — |
| `close_cost` | `0.0015` | 卖出成本（万十五） | — |

### 修改方式

```bash
# 统一修改（所有轮次生效）
vim .env

# 临时覆盖（单次运行）
export topk=30 && qrun conf_combined_factors.yaml
```

---

## 参数调优指南

回测后根据指标调整参数，形成 **因子→回测→调参→再回测** 的闭环：

| 问题现象 | 诊断 | 调整方案 |
|---------|------|---------|
| IC 低（<0.02） | 因子本身无效 | 换因子，不是调参数能解决的 |
| IC 高但年化收益低 | 选股/持仓策略问题 | `topk`↓ 或 `n_drop`↑ |
| train 好 test 差 | 过拟合 | `max_depth`↓, `num_leaves`↓, `lambda_l1/l2`↑ |
| train/test 都差 | 欠拟合 | `max_depth`↑, `num_leaves`↑, `learning_rate`↑ |
| 换手率太高 | 信号太嘈杂 | `n_drop`↓, 或因子加平滑（rolling） |
| 最大回撤太大 | 集中度过高 | `topk`↑ 分散持仓 |

**建议流程**：
1. 先用默认参数跑一轮基线
2. 看指标→定位问题→调 1-2 个参数
3. 不要同时调多个参数（无法归因）

---

## 因子渐进策略（对标 RD-Agent）

遵循 [rd-agent-specs.md](./references/rd-agent-specs.md) 中的 `假设生成与因子渐进策略`，因子研发必须循序渐进：

| 阶段 | 轮次 | 策略 | 参数 |
|------|------|------|------|
| **简单验证** | 1-5 | 简单因子（动量、反转、量价比），每轮 1-2 个 | 默认参数 |
| **深入挖掘** | 5-15 | 多窗口期、多字段交叉、非线性变换，每轮 2-4 个 | 微调 `topk`/`n_drop` |
| **高级探索** | 15+ | 复杂组合因子、统计因子（偏度/峰度/分位数），每轮 3-5 个 | 精调模型参数 |

### 关键规则

1. **每轮 1-5 个因子**，不超过 5 个
2. **简单有效优先** — 先做大概率有效的简单因子，说明预期有效的理由
3. **渐进增加复杂度** — 简单因子验证后才做组合/复杂因子
4. **连续失败必须换方向** — 连续 3 轮未超 SOTA，切换到全新因子类型（详见 [metrics-guide.md](./references/metrics-guide.md) 中的 `连续失败判断`）
5. **已入库因子不重复** — 超 SOTA 的因子已在 `sota_combined.parquet` 中，不要重新实现

### 陷阱

- **时间泄露**：shift 必须为正数
- **过拟合**：train 好 test 差 → 降 `max_depth`/`num_leaves`
- **因子共线性**：IC 去重率 > 80% → 换全新维度
- **空结果**：禁止对结果 `dropna()`

---

## 已知问题 & 注意事项

| 问题 | 说明 | 解决方案 |
|------|------|----------|
| Docker 符号链接 | Docker `-v` 挂载后容器内符号链接指向宿主机路径，不可用 | 用 `cp` 代替 `ln -sf` |
| Docker 文件权限 | 容器以 root 创建的文件（mlruns/）宿主机普通用户无法删除 | `run_backtest.sh` 自动用 Docker 清理旧产出 |
| 本地 Python 依赖 | `validate_factor.py` / `merge_factors.py` 需要 pandas+tables | 开始前运行 `main_setup.sh` 确认 |
| infer_processors | `conf_baseline.yaml` 含 RobustZScoreNorm + Fillna；`conf_combined_factors.yaml` 不含（LightGBM 对缩放不敏感，与 RD-Agent 一致） | 基线模板勿删除；合并因子模板无需添加 |

---

## 错误知识库（Error Knowledge Base）

### 工作原理

借鉴 RD-Agent CoSTEER 的 `working_trace_error_analysis` 机制：
- **自动采集**：`validate_factor.py`、`run_backtest.sh`、`merge_factors.py` 失败时自动调用 `collect_error.py record` 写入 `$EXP_ROOT/error_knowledge.jsonl`
- **Agent 标注**：Agent 定位根因后，调用 `collect_error.py annotate` 补充原因和修复方法
- **下轮注入**：每轮开始前 Agent 调用 `summary`，历史经验自动注入上下文，避免重复犯错

### 数据结构（`error_knowledge.jsonl`，每行一条）

```json
{"id": "err_abc123", "round": 1, "stage": "validate", "factor": "drop_rebound_vol",
 "error_type": "high_nan", "error_msg": "NaN ratio 97% (>80%)",
 "root_cause": "close 用了未来数据，Ref($close,-1) 方向写反",
 "fix": "改为 Ref($close,1)/$close - 1", "fixed": true}
```

### Agent 错误处理规范（必须遵守）

**遇到任何失败时，Agent 必须按以下流程操作：**

```bash
# Step 1: 错误已被自动记录（查看 record 输出的 ID）
# Step 2: 定位根因后立即标注（不要跳过！）
$PYTHON_BIN "$EXP_ROOT/collect_error.py" annotate \
    --exp-root "$EXP_ROOT" --id err_abc123 \
    --root-cause "close 用了未来数据，Ref 方向写反" \
    --fix "改为 Ref(\$close,1)/\$close - 1" --fixed

# Step 3: 修复代码后重新验证
$PYTHON_BIN "$EXP_ROOT/validate_factor.py" "$ROUND_DIR/{因子名}"
```

**错误阶段分类：**

| `--stage` | 对应脚本 | 典型错误类型 |
|-----------|----------|-------------|
| `validate` | `validate_factor.py` | `high_nan`, `exec_failed`, `index_error` |
| `factor_exec` | Docker `factor.py` | `exec_failed`, `timeout`, `memory_error` |
| `merge` | `merge_factors.py` | `dedup_all`, `data_missing`, `format_error` |
| `backtest` | `run_backtest.sh` / `qrun` | `backtest_error`, `docker_error` |

### 手动记录错误（自动采集没覆盖到的情况）

```bash
$PYTHON_BIN "$EXP_ROOT/collect_error.py" record \
    --exp-root "$EXP_ROOT" --round $ROUND \
    --stage backtest \
    --error "PortAnaRecord IndexError: 交易所初始化失败，codes 传了 dict 而非 list"
```

---

## 脚本退出码说明

脚本通过退出码传递语义信息，Agent 应根据退出码决定下一步行动：

| 脚本 | 退出码 | 含义 | Agent 应对 |
|------|--------|------|------------|
| `validate_factor.py` | `0` | 验证通过 | 继续下一步 |
| `validate_factor.py` | `1` | 验证失败（代码错误/格式问题） | 修改 factor.py 后重新验证 |
| `merge_factors.py` | `0` | 合并成功 | 继续回测 |
| `merge_factors.py` | `1` | 没找到有效因子文件 | 检查 result.h5 是否生成 |
| `merge_factors.py` | `2` | **所有新因子与 SOTA 高度相关，全部被去重** | ⚠️ 需要换因子思路，不能只微调参数 |
| `run_backtest.sh` | `0` | 回测+结果提取成功 | 继续分析 |
| `run_backtest.sh` | `1` | 回测失败（重试 3 次后仍失败） | 查看 `$ROUND_DIR/docker_run.log` 排查原因 |

---

> 📌 完整因子示例库（8 个验证示例 + 常见错误速查）见 [references/factor-examples.md](./references/factor-examples.md)
> 📖 假设-反馈循环规范见 [references/hypothesis-feedback.md](./references/hypothesis-feedback.md)
> 📖 RD-Agent 完整规范（含因子渐进策略、数据注释规范）见 [references/rd-agent-specs.md](./references/rd-agent-specs.md)
