---
name: fin-model
description: 'Qlib AI 模型自动优化 Agent。设计 PyTorch 模型架构、生成代码、Docker+Qlib 回测、分析训练日志、循环优化。Use when: 模型优化、AI模型、PyTorch模型、神经网络、模型架构搜索、fin model、优化模型。'
argument-hint: '描述模型优化方向，例如："尝试 LSTM + Attention 结合时序特征"'
---

# Qlib AI 模型自动优化 Agent

## 概述

用户描述模型优化方向，Agent 负责：
1. **理解方向** — 有疑问就追问
2. **给方案** — 展示假设 + 模型 Specification（架构/超参/类型），用户确认后才写代码
3. **写代码** — 实现 PyTorch 模型 (`model.py`)
4. **快速验证** — forward pass <30秒验证代码正确性
5. **Docker 回测** — Qlib GeneralPTNN 训练 + 策略回测
6. **分析反馈** — 训练日志 + 指标对比，建议下一步

**核心原则**：
- **先验证后回测**
- **每轮只设计一个模型**（对齐 RD-Agent 设计）
- **用户不需要懂 PyTorch** — Agent 自主设计架构
- 每轮都 **询问用户** 确认

> **来源**: 本 skill 复刻自 [RD-Agent](../../RD-Agent/) 的 Qlib 模型优化循环（`rdagent/scenarios/qlib/`），
> 将其自动化 R&D 循环转化为交互式 Copilot 技能。

---

## 前置条件 & 环境初始化

**`main_setup.sh` 是唯一的环境入口脚本** — 检查一切、能修就自动修、修不了打印命令让用户修。

```bash
bash .github/skills/fin-model/scripts/main_setup.sh
```

该脚本自动检查并修复：
1. **Docker 守护进程** — 运行状态
2. **Docker 镜像** — 不存在则自动构建
3. **Docker GPU** — 有 GPU 则自动安装 nvidia-container-toolkit 并验证
4. **Qlib 数据** — 不存在则自动下载
5. **Python 环境** — 需要 pandas + tables + numpy + torch

---

## Agent 环境检查流程（⚠️ 必须遵循）

**每次新对话开始时，Agent 按以下流程操作：**

1. Agent 执行 `bash $MODEL_SKILL_DIR/scripts/main_setup.sh`
2. **全部通过** → 继续到阶段 0（工作区初始化）
3. **有失败项** → Agent 把报错信息展示给用户，告诉用户：
   - 按 `main_setup.sh` 输出的提示修复问题
   - 修复后自己在终端跑一遍 `bash .github/skills/fin-model/scripts/main_setup.sh` 确认全部 ✅
   - 回来告诉 Agent "环境好了"
4. 用户确认后 → Agent 继续

**⚠️ Agent 绝不跳过此步骤。环境未就绪时不得执行任何回测操作。**

---

## 环境变量（.env）

Agent 必须了解的关键变量（由 `.env` 管理）：

| 变量 | 含义 | 谁用 |
|------|------|------|
| `MODEL_SKILL_DIR` | 本 skill 目录 | 所有脚本 |
| `MODEL_EXP_ROOT` | 模型工作区路径 | 所有脚本 |
| `PYTHON_BIN` | 本地 Python 路径（含 torch） | validate_model.py |
| `DOCKER_IMAGE` | Docker 镜像名 | run_backtest.sh |
| `QLIB_DATA_DIR` | Qlib 数据目录 | run_backtest.sh |
| `ACTIVE_FEATURE_SET` | 基础特征集 (ALPHA20/ALPHA158) | common.sh |
| `n_epochs` | 训练轮次 | YAML 模板 |
| `lr` | 学习率 | YAML 模板 |
| `early_stop` | 早停轮次 | YAML 模板 |
| `batch_size` | 批大小 | YAML 模板 |
| `weight_decay` | 权重衰减 | YAML 模板 |
| `dataset_cls` | 数据集类型 | YAML 模板 |
| `num_timesteps` | 时序窗口 | YAML 模板 |

---

## 工作流

### 阶段 0: 工作区初始化

**环境确认就绪后，首次使用时执行一次**：
```bash
bash $MODEL_SKILL_DIR/scripts/init_workspace.sh
```

如果环境未就绪（Docker 镜像或 Qlib 数据缺失），该脚本会报错并提示运行 `main_setup.sh`。

记住 `MODEL_EXP_ROOT` 路径，后续所有步骤使用此变量。

---

### 阶段 1: 理解 & 设计（交互式）

#### 1.0 理解用户想法

- 用户描述模型优化方向（如 "试试 Transformer"、"之前的 GRU 过拟合了"）
- Agent **复述理解** + **追问最多 1-2 个问题**
- 如果是第 2+ 轮，先汇报上轮结果

#### 1.1 读取历史错误（每轮必做）

```bash
$PYTHON_BIN collect_error.py summary --exp-root $MODEL_EXP_ROOT --round $ROUND
```

如果有历史错误 → 内化教训，设计时规避。
如果为空 → "暂无历史错误"（正常）。

#### 1.2 读取上轮挑战（第 2 轮起必做）

分析上一轮的 `analysis.json` 和 `docker_run.log`：
- 过拟合？欠拟合？Early stopping 时机？
- 哪些指标改善/恶化？
- 提炼 `challenges.json`（参考 [report-templates.md](./references/report-templates.md)）

后续假设 **必须引用挑战 ID**。

#### 1.3 生成假设 + 模型 Specification ⏸️ **用户确认点 #1**

**必须读取**：[hypothesis-feedback.md](./references/hypothesis-feedback.md)

Agent 展示：

```
📋 模型优化假设:
  假设: "[精确、可测试的陈述，2-3句]"
  理由: "[基于证据，≤2句]"

📐 模型 Specification:
  名称: [模型名]
  类型: TimeSeries / Tabular
  架构:
    - [逐层描述]
  超参:
    n_epochs=[值], lr=[值], batch_size=[值], ...

✅ 这样做可以吗？
```

**⚠️ 等待用户确认 → 不确认不写代码！**

#### 1.4 咨询不确定项 ⏸️ **用户确认点 #2（可选）**

如果存在设计选择不确定的地方，**最多问 1-2 个选择题**：
- "hidden_dim 用 64 还是 128？"
- "先试 TimeSeries 还是 Tabular？"
- **绝不问开放式问题**

用户不回复 → 使用默认策略继续（标注 "⚠️ 使用默认策略"）。
**默认策略**: TimeSeries 优先、简单架构优先、保守超参。

---

### 阶段 2: 编码 & 验证

#### 2.1 编写 model.py

**必须读取**：[model-code-spec.md](./references/model-code-spec.md)
**参考示例**：[model-examples.md](./references/model-examples.md)

**遵循规则**：
- `torch.nn.Module` 子类
- `__init__(self, num_features, num_timesteps=None)` 签名
- `forward(self, x)` → `(batch_size, 1)`
- 文件末尾 `model_cls = YourModelName`
- **不写训练循环、不做特征处理、不 import qlib**

**同时生成** `model_meta.json`（模型名、类型、架构描述、超参）。

存放位置：`$MODEL_EXP_ROOT/round_$N/<model_name>/model.py`

**⚠️ 写代码前必须检查 Step 1.1 历史错误，避免重复犯错！**

#### 2.2 快速验证（<30秒）

```bash
$PYTHON_BIN validate_model.py "$ROUND_DIR/<model_name>"
```

**验证项**（参考 RD-Agent `model_execute_template_v1.txt`）：
- ✓ `model_cls` 导入成功
- ✓ 是 `nn.Module` 子类
- ✓ forward pass 无报错
- ✓ 输出 shape = `(batch, 1)`
- ✓ 无 NaN/Inf
- ✓ 参数量合理（<100M）

**退出码**：
- `0` ✅ → 进入阶段 3
- `1` ❌ → **修改代码 → 重新验证（循环直到通过）**

如果验证失败，Agent 必须：
1. 读取错误信息
2. 立即标注根因：`$PYTHON_BIN collect_error.py annotate ...`
3. 修改 model.py
4. 重新执行验证

---

### 阶段 3: 回测 & 分析

#### 3.1 Docker 回测（5-15 分钟）

```bash
bash run_round.sh "$ROUND_DIR"
```

`run_round.sh` 自动编排：
1. 快速验证（二次确认）
2. 复制 model.py + 配置到工作目录
3. Docker 执行 `qrun conf.yaml`（自动选择 baseline/sota 配置）
4. 提取结果 (`read_exp_res.py`)
5. 分析结果 (`analyze_results.py`)

**环境变量透传**（对齐 RD-Agent `model_runner.py`）：
- `PYTHONPATH=./`
- `train_start/end`, `valid_start/end`, `test_start/end`
- `feature_names`, `feature_expressions`
- `n_epochs`, `lr`, `early_stop`, `batch_size`, `weight_decay`
- `dataset_cls`, `step_len`, `num_timesteps`, `num_features`
- `QLIB_PROVIDER_URI=/qlib_data`（Docker 内固定值）

**退出码**：
- `0` ✅ → 继续
- `1` ❌ → 检查 `docker_run.log` → 诊断 → 修复或汇报

#### 3.2 训练日志分析（必做）

**对齐 RD-Agent `feedback.py` 的 Training Log 分析逻辑。**

```bash
cat "$ROUND_DIR/docker_run.log" | grep -E "early stopping|loss|mse|valid|train"
```

**4 项必查**：
1. **Early Stopping 时机**: <30轮 → lr 太高或模型不稳定
2. **Loss 趋势**: valid loss 上升 → 过拟合
3. **收敛情况**: loss 未降 → 模型/lr 有问题
4. **训练时间**: >10分钟 → 模型过大

#### 3.3 SOTA 更新

```bash
$PYTHON_BIN update_sota.py "$MODEL_EXP_ROOT" "$ROUND_DIR" $ROUND
```

如果更新 → model.py 自动备份到 `model_sota/round_N_*.py`。

---

### 阶段 4: 反馈 & 迭代 ⏸️ **用户确认点 #3**

**必须读取**：[hypothesis-feedback.md](./references/hypothesis-feedback.md)
**参考指标解读**：[metrics-guide.md](./references/metrics-guide.md)

#### 4.1 生成结构化反馈

按照 RD-Agent `model_feedback_generation` 格式分析：
```json
{
  "Observations": "训练日志 + 指标对比",
  "Feedback for Hypothesis": "确认/反驳",
  "New Hypothesis": "修正方向",
  "Reasoning": "理由",
  "Decision": true/false
}
```

#### 4.2 写报告

参照 [report-templates.md](./references/report-templates.md)：
- 写 `$ROUND_DIR/report.md`
- 追加 `$MODEL_EXP_ROOT/summary.md`

#### 4.3 展示给用户

**必须包含**：
1. 📊 **指标对比表**: 本轮 vs SOTA（三列表格）
2. 🔍 **训练日志分析**: Early stopping / Loss / 过拟合
3. 💡 **反馈**: Observations + Hypothesis Evaluation
4. 🎯 **下一步建议**（4 选 1）:
   - **深化**: 在当前架构上改进（推荐，如果接近 SOTA）
   - **换方向**: 尝试全新架构（推荐，如果差距大）
   - **微调**: 只调超参，不改架构
   - **停止**: 如果满意或多轮失败

**等待用户选择 → 用户选择后回到阶段 1**

---

### 循环退出条件

1. 用户明确说 "停止" / "够了" / "结束"
2. 连续 3 轮未超越 SOTA → Agent 建议停止
3. 指标收敛（连续 5 轮综合评分变化 <1%）
4. 用户满意当前结果

---

## 决策点总结

| # | 步骤 | Agent 等待 | 继续条件 |
|---|------|-----------|---------|
| ⏸️ 1 | 1.3 | 用户确认模型方案 | 用户说 ✅ |
| ⏸️ 2 | 1.4 | 用户回答选择题 | 用户回复或超时（用默认策略） |
| ⏸️ 3 | 4.3 | 用户选择下一步 | 用户做出选择 |

**Agent 自主决策**（不需用户确认）：

| 步骤 | 决策 | True → | False → |
|------|------|--------|---------|
| 2.2 | 验证通过？ | → 阶段 3 | → 修代码 → 重验证 |
| 3.1 | 回测成功？ | → 3.2 分析 | → 检查日志 → 修复 |
| 3.3 | 超越 SOTA？ | → 建议深化 | → 建议换方向 |

---

## 架构设计原则（对齐 RD-Agent 8 条规则）

**必须读取**：[model-architecture-guide.md](./references/model-architecture-guide.md)

1. 分析实验轨迹，找架构弱点
2. 参考 last/SOTA 实验
3. 首轮从简单架构开始
4. 连续失败 → 回归简单
5. 只关注 PyTorch 架构（层、激活、正则）
6. 不做特征处理
7. 超参调整也是有效策略
8. 追求 NeurIPS/ICLR 级别创新

---

## 模型代码规范

**必须读取**：[model-code-spec.md](./references/model-code-spec.md)

核心要点：
- `torch.nn.Module` + `model_cls = YourModel`
- `__init__(num_features, num_timesteps=None)`
- `forward(x)` → `(batch, 1)`
- 不写训练循环、数据加载、特征处理

**示例代码**：[model-examples.md](./references/model-examples.md)

---

## 独立性说明

本 skill 是**完全独立**的，不依赖 fin-factor skill：
- **独立的** `main_setup.sh` — 唯一环境入口，自主检查 Docker、GPU、Qlib 数据、Python
- **独立的** Dockerfile — `docker/Dockerfile` 
- **独立的** 脚本和配置 — 所有文件自包含在 `fin-model/` 目录中

**可选联动**（非必须）：
- 如果用户手动将 SOTA 因子文件（`sota_combined.parquet`）复制到模型工作区，
  回测会自动使用增强特征配置（`conf_sota_model.yaml`）
- 需要用户在 `.env` 中设置 `FACTOR_WORKSPACE_DIR` 才能自动发现因子文件

---

## 错误处理

### 验证失败
- 读取 `validate_model.py` 输出的错误信息
- 标注根因: `$PYTHON_BIN collect_error.py annotate --exp-root $MODEL_EXP_ROOT --id <id> --root-cause "..." --fix "..." --fixed`
- 修改代码 → 重新验证

### 回测失败
- 检查 `$ROUND_DIR/docker_run.log`
- 常见原因：输出 shape 错误、NaN/Inf、OOM
- 错误自动记录到 `error_knowledge.jsonl`

### 超参问题
- 训练日志分析发现过拟合/欠拟合 → 在 `model_meta.json` 中调整 `training_hyperparameters`
- `run_backtest.sh` 会从环境变量读取超参（可通过 `export lr=0.0001` 临时覆盖）

---

## 文件布局

```
$MODEL_EXP_ROOT/
├── conf_baseline_model.yaml    ← Alpha158 + 新模型
├── conf_sota_model.yaml        ← Alpha158 + SOTA因子 + 新模型
├── read_exp_res.py             ← 结果提取
├── validate_model.py           ← 快速验证
├── run_backtest.sh             ← Docker 回测
├── run_round.sh                ← 一键编排
├── analyze_results.py          ← 结果分析
├── update_sota.py              ← SOTA 更新
├── collect_error.py            ← 错误知识库
├── sota_record.json            ← SOTA 追踪
├── model_sota/                 ← SOTA model.py 备份
│   ├── current_sota_model.py
│   └── round_1_GRU_v1.py
├── summary.md                  ← 累积实验摘要
├── round_1/
│   ├── GRU_v1/
│   │   ├── model.py            ← LLM 生成的模型代码
│   │   └── model_meta.json     ← 模型元信息
│   ├── model.py                ← 复制到顶层（qrun 用）
│   ├── model_meta.json
│   ├── conf_baseline_model.yaml
│   ├── read_exp_res.py
│   ├── qlib_res.csv            ← 回测指标
│   ├── ret.pkl                 ← 收益曲线
│   ├── docker_run.log          ← Docker 训练日志
│   ├── analysis.json           ← 结构化分析
│   └── report.md               ← 本轮报告
└── round_2/
    └── ...
```
