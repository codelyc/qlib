---
name: fin-quant
description: 'Qlib 联合因子+模型自动优化 Agent。用户主导因子/模型切换节奏，Bandit 给参考建议，SOTA 因子⇄模型自动交叉集成。Use when: 量化策略优化、联合优化、因子+模型、fin quant、quant optimization。'
argument-hint: '描述优化目标，例如："帮我优化一个量化选股策略"'
---

# Qlib 联合因子+模型自动优化 Agent

## 概述

**解决的问题**: fin-factor 和 fin-model 各自独立运行，因子调好了模型没跟上，模型调好了没用最新因子——两边割裂。

**本 skill 的做法**（参考 [RD-Agent QuantRDLoop](../../RD-Agent/rdagent/app/qlib_rd_loop/quant.py)）：
1. **统一工作区** — 因子和模型在同一个 workspace 迭代
2. **用户主导切换** — 用户决定"做因子"还是"做模型"，每轮结束都问
3. **Bandit 参考建议** — Thompson Sampling 给出建议（"因子 IC 够了，建议切模型"），用户可忽略
4. **自动交叉集成** — 切到模型时 SOTA 因子自动注入；切到因子时 SOTA 模型可用于评估
5. **CoSTEER 知识回溯** — 写代码前 Agent 必须读取完整历史轨迹，避免重复犯错

**核心原则**：用户不需要手动搬运数据；每轮都询问用户；先因子后模型。

---

## 架构：调用而非复制

fin-quant 是编排层，**调用 fin-factor 和 fin-model 的现有脚本**，自身不复制脚本：

```
fin-quant (编排层)
  ├── action_advisor.py         ← Bandit 建议（仅参考）
  ├── prepare_cross_data.py     ← SOTA 因子⇄模型自动注入
  ├── run_quant_round.sh        ← 统一编排
  │    ├── action=factor 时:
  │    │    └── 调用 $SKILL_DIR/scripts/ 的因子流程
  │    └── action=model 时:
  │         └── 调用 $MODEL_SKILL_DIR/scripts/ 的模型流程
  ├── update_quant_sota.py      ← 统一 SOTA 管理
  └── quant_trace.py            ← 统一追踪 + Bandit 状态
```

改 fin-factor/fin-model 的任何脚本 → fin-quant 自动受益。

---

## 前置条件

**⚠️ 开始前，必须先执行环境初始化脚本：**

```bash
bash .github/skills/fin-quant/scripts/main_setup.sh
```

该脚本分 4 个阶段检查：
1. **基础环境** — 调用 fin-factor 的 main_setup.sh（Docker + 镜像 + Qlib 数据 + Python）
2. **模型环境** — PyTorch + GPU（Docker GPU 可选但推荐）
3. **子 Skill 完整性** — 验证 fin-factor 和 fin-model 的脚本/YAML 模板都存在
4. **fin-quant 自身** — 验证编排脚本 + numpy（Bandit 需要）

全部通过后才开始工作。

### `.env` 环境配置

项目根目录的 `.env` 是所有脚本的**唯一配置中心**。fin-quant 需要的变量：

| 变量 | 含义 |
|------|------|
| `QUANT_SKILL_DIR` | 本 skill 目录 |
| `QUANT_EXP_ROOT` | 联合优化工作区 |
| `SKILL_DIR` | fin-factor skill 目录（被调用） |
| `MODEL_SKILL_DIR` | fin-model skill 目录（被调用） |
| `PYTHON_BIN` | 本地 Python |
| `DOCKER_IMAGE` | Docker 镜像 |
| `QLIB_DATA_DIR` | Qlib 数据 |

---

## 完整工作流

### 阶段 0: 初始化工作空间（首次）

```bash
bash $QUANT_SKILL_DIR/scripts/init_workspace.sh [workspace_name]
```

产出：`$QUANT_EXP_ROOT/` 包含因子+模型两套 YAML 模板、数据文件、追踪文件。

**记住 `QUANT_EXP_ROOT` 路径，后续所有步骤使用。**

---

### 阶段 1: 选择方向 ⏸️ **用户确认点 #1**

#### 1.0 获取建议（三选一）

Agent 可通过三种方式获取下一步建议：

**方式 A — Bandit 数值建议**（默认）：
```bash
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py suggest \
    --exp-root $QUANT_EXP_ROOT
```

**方式 B — LLM 深度分析**（Agent 自行推理决策）：
```bash
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py llm-suggest \
    --exp-root $QUANT_EXP_ROOT
```
输出完整 context JSON：Bandit 建议 + 历史摘要 + 最后一轮反馈 + RAG 提示 + 累积知识。
Agent 读取后自行分析，给出推理过程和建议。

**方式 C — 用户直觉**：直接问用户。

Agent 综合以上信息展示给用户：

> 📊 **实验状态**: 因子 N 轮, 模型 M 轮
>
> 🎯 **Bandit 建议**: [factor/model] (得分: factor=X.XX, model=X.XX)
>   理由: [人话解释]
>
> 🧠 **Agent 分析**（如用了 llm-suggest）: [Agent 的推理和建议]
>
> 💡 **RAG 提示**: [当前阶段应关注的方向]
>
> **你想这轮做什么？**
> 1. 做因子（挖新因子/优化因子）
> 2. 做模型（优化模型架构/超参）
> 3. 停止

**等待用户选择。用户可以忽略 Bandit / Agent 建议。**

#### 1.1 读取历史（CoSTEER 智能知识回溯，每轮必做）

**Agent 必须读取以下文件，自己理解和避坑：**

1. **智能过滤的历史轨迹**（⭐ 首选，减少噪音）：
   ```bash
   # 做因子时: 看所有因子轮 + 最近一个 SOTA 模型轮
   $PYTHON_BIN $QUANT_SKILL_DIR/scripts/quant_trace.py show --exp-root $QUANT_EXP_ROOT --focus factor
   # 做模型时: 看所有模型轮 + 最近一个 SOTA 因子轮
   $PYTHON_BIN $QUANT_SKILL_DIR/scripts/quant_trace.py show --exp-root $QUANT_EXP_ROOT --focus model
   ```
   > 📌 **智能过滤原理** (参考 RD-Agent `quant_proposal.py`):
   > 做因子时 Agent 不需要看所有模型轮的细节，只需知道最好的模型是什么;
   > 做模型时同理。这样 Agent 聚焦当前方向，减少 token 浪费。

2. **错误知识库**: `$PYTHON_BIN $SKILL_DIR/scripts/collect_error.py summary --exp-root $QUANT_EXP_ROOT --round $ROUND`
3. **累积实验摘要**: `cat $QUANT_EXP_ROOT/summary.md`（如存在）
4. **上轮同类型代码**: 上轮因子的 `factor.py` 或上轮模型的 `model.py`——借鉴/避坑

> 🔑 **CoSTEER 精髓**: Agent 就是 LLM，不需要检索脚本。
> 直接告诉 Agent 文件位置，Agent 自己读、自己理解、自己避坑。
>
> 💡 **concise_knowledge**: 历史中每轮的核心洞察会自动展示在 `show` 输出末尾。
> Agent 写代码前先看这些知识，避免重复犯错。

---

### 阶段 2: 设计 & 编码（路由到子 skill）

根据用户选择的方向，**完全遵循对应子 skill 的设计流程**：

#### 用户选了"做因子"

遵循 **fin-factor SKILL.md** 的第 1-3 步：
- 第 1 步：理解想法 → 追问 → 展示因子方案
- 第 1.5 步：因子 Specification（严格参考 [rd-agent-specs.md](../../fin-factor/references/rd-agent-specs.md)）
- 第 1.7 步：挑战提炼（第 2 轮起）
- 第 1.8 步：不确定项咨询
- ⏸️ **用户确认方案**
- 第 2 步：编写 factor.py
- 第 3 步：快速验证

**因子代码规范**: 见 fin-factor 的 [factor-code-spec.md](../../fin-factor/references/factor-code-spec.md)

#### 用户选了"做模型"

遵循 **fin-model SKILL.md** 的阶段 1-2：
- 1.0：理解方向
- 1.1-1.2：历史错误 + 挑战
- 1.3：假设 + 模型 Specification
- ⏸️ **用户确认方案**
- 2.1：编写 model.py + model_meta.json
- 2.2：快速验证

**模型代码规范**: 见 fin-model 的 [model-code-spec.md](../../fin-model/references/model-code-spec.md)

---

### 阶段 3: 回测（自动交叉集成）

#### 3.1 一键执行

```bash
ROUND=1; ROUND_DIR="$QUANT_EXP_ROOT/round_$ROUND"
bash $QUANT_SKILL_DIR/scripts/run_quant_round.sh "$ROUND_DIR" "$ACTION"
```

`run_quant_round.sh` 自动编排：
1. **交叉集成** (`prepare_cross_data.py`)：
   - model 轮 → 自动复制 `sota_combined.parquet` 到 round 目录
   - factor 轮 + SOTA 模型存在 → 自动复制 `current_sota_model.py` 到 round 目录
2. **路由**: factor → 调用 `$SKILL_DIR/scripts/run_round.sh`；model → 调用 `$MODEL_SKILL_DIR/scripts/run_round.sh`
3. **SOTA 更新** (`update_quant_sota.py`)

#### 3.2 训练日志分析（必做）

```bash
cat "$ROUND_DIR/docker_run.log" | grep -E "early stopping|loss|mse|valid|train|feature importance"
```

**4 项必查**（与 fin-factor/fin-model 一致）：
1. Early Stopping 时机
2. Loss 趋势
3. 收敛情况 / 特征重要性
4. 训练时间

---

### 阶段 4: 记录轨迹 + 结构化反馈（CoSTEER）

回测完成后，**必须记录完整轨迹 + 结构化反馈 + concise_knowledge**：

```bash
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/quant_trace.py record \
    --exp-root $QUANT_EXP_ROOT \
    --round $ROUND \
    --action $ACTION \
    --task "任务描述（如：大跌放量反弹因子）" \
    --code-path "round_$ROUND/<name>/factor.py" \
    --result success \
    --is-sota \
    --metrics '{"ic":0.04,"icir":0.45,"arr":0.08,"sharpe":1.2}' \
    --feedback '{"observations":"IC +40%, ARR +32%","hypothesis_evaluation":"假设验证","new_hypothesis":"加平滑+尝试波动率","reasoning":"信号尖锐致MDD扩大","replace_sota":true}' \
    --concise-knowledge "放量反弹因子IC稳定但需平滑；波动率维度尚未探索"
```

**⚠️ 三项必填**（参考 [feedback-format.md](./references/feedback-format.md)）：
1. **`--feedback`**: 结构化 JSON（observations, hypothesis_evaluation, new_hypothesis, reasoning, replace_sota）
2. **`--concise-knowledge`**: 1-2 句核心洞察（下一轮 Agent 会读到）
3. **`--is-sota`**: 如果本轮成为新 SOTA 加此 flag

**注意**: 成功和失败都要记录！失败轮次也是宝贵的经验。

---

### 阶段 5: 反馈 & 下一轮 ⏸️ **用户确认点 #3**

#### 5.1 生成结构化反馈

按照 **[feedback-format.md](./references/feedback-format.md)** 格式分析结果（⚠️ 必须是结构化 JSON）。

因子轮参考 [fin-factor/hypothesis-feedback.md](../../fin-factor/references/hypothesis-feedback.md)。
模型轮参考 [fin-model/hypothesis-feedback.md](../../fin-model/references/hypothesis-feedback.md)。

#### 5.2 写报告

```bash
# 写 round 报告
$ROUND_DIR/report.md

# 追加到总摘要
$QUANT_EXP_ROOT/summary.md
```

#### 5.3 展示给用户（含 Bandit 建议）

```bash
# 获取 Bandit 对下一轮的建议
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py suggest \
    --exp-root $QUANT_EXP_ROOT

# 或使用 LLM 深度分析 (Bandit + 历史 + RAG + 累积知识)
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py llm-suggest \
    --exp-root $QUANT_EXP_ROOT
```

Agent 向用户展示：

> 📊 **本轮结果** (Round N, action=$ACTION):
>
> | 指标 | 本轮 | SOTA |
> |------|------|------|
> | IC | 0.040 | 0.035 |
> | 年化收益 | 8.2% | 6.5% |
> | 夏普比率 | 1.20 | 0.95 |
> | ... | ... | ... |
>
> ✅ 超越 SOTA! / ❌ 未超越 SOTA
>
> 🔍 **训练日志**: [early stopping/loss/过拟合分析]
>
> 🎯 **Bandit 建议下一轮**: [factor/model] (得分: X.XX vs X.XX)
>   理由: [人话]
>
> **你想下一步做什么？**
> 1. 继续当前方向 (${ACTION})
> 2. 切换到 [factor/model]
> 3. 停止

**等待用户选择 → 回到阶段 1**

---

## 交叉集成说明

### SOTA 因子 → 模型训练（自动）

当用户切到模型轮时：
1. `prepare_cross_data.py` 自动检测 `$QUANT_EXP_ROOT/sota_combined.parquet`
2. 如存在 → 复制到 `$ROUND_DIR/combined_factors_df.parquet`
3. 回测自动使用 `conf_sota_model.yaml`（Alpha158 + SOTA 因子 + 新模型）
4. `num_features` 自动计算（base + SOTA factor columns）

### SOTA 模型 → 因子评估（自动）

当用户切到因子轮时：
1. `prepare_cross_data.py` 自动检测 `$QUANT_EXP_ROOT/current_sota_model.py`
2. 如存在 → 复制到 `$ROUND_DIR/model.py`
3. 因子除了 LightGBM 评估外，还可用 `conf_factor_with_sota_model.yaml` 做 SOTA 模型评估

---

## RAG 动态策略提示

Agent 根据当前进度自动调整研发策略（参考 RD-Agent `quant_proposal.py`）：

### 因子方向

| 阶段 | 轮次 | 策略 |
|------|------|------|
| 探索期 | 前 6 轮 | 尝试简单、快速的因子，覆盖不同视角（动量、反转、量价、波动率）。优先验证思路 |
| 深入期 | 6 轮后 | 尝试高 IC 因子（多窗口、交叉特征、统计类），**避免与 SOTA 重复**（IC 去重 >0.99 会被删） |

### 模型方向

| 阶段 | 轮次 | 策略 |
|------|------|------|
| 基线期 | 第 1-2 轮 | GRU / LSTM 等经典时序模型，控制参数量 |
| 改进期 | 第 3-5 轮 | ALSTM / TCN 等改进架构，调超参 |
| 创新期 | 5 轮后 | Transformer / Hybrid 等复杂架构，但**控制模型规模** |

> 💡 这些策略通过 `llm-suggest` 的 `rag_guidance` 字段自动注入 Agent context。

---

## 循环退出条件

1. 用户明确说"停止" / "够了" / "结束"
2. 连续 3 轮（同方向）未超越 SOTA → Agent 建议切换方向或停止
3. 用户满意当前结果

---

## 决策点总结

| # | 步骤 | Agent 等待 | 继续条件 |
|---|------|-----------|---------|
| ⏸️ 1 | 阶段 1 | 用户选 factor/model/停止 | 用户选择 |
| ⏸️ 2 | 阶段 2 | 用户确认因子/模型方案 | 用户说 ✅ |
| ⏸️ 3 | 阶段 5 | 用户选下一步 | 用户选择 |

**Agent 自主决策**（不需用户确认）：

| 步骤 | 决策 | True → | False → |
|------|------|--------|---------|
| 验证 | 通过？ | → 回测 | → 修代码 → 重验证 |
| 回测 | 成功？ | → 分析 | → 检查日志 → 修复 |
| SOTA | 超越？ | → 建议继续 | → 建议换方向 |

---

## 单轮速查

```bash
ROUND=1; ACTION=factor  # 或 model
ROUND_DIR="$QUANT_EXP_ROOT/round_$ROUND"

# ── 因子轮 ──
mkdir -p "$ROUND_DIR/{factor_name}"
# Agent 写 factor.py ...
cp "$QUANT_EXP_ROOT/daily_pv_debug.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
$PYTHON_BIN "$SKILL_DIR/scripts/validate_factor.py" "$ROUND_DIR/{factor_name}"
cp "$QUANT_EXP_ROOT/daily_pv.h5" "$ROUND_DIR/{factor_name}/daily_pv.h5"
docker run --rm -v "$ROUND_DIR/{factor_name}":/workspace/qlib_workspace/ \
  -v "$PROJECT_ROOT/qlib/data":/qlib_data --shm-size=16g \
  $DOCKER_IMAGE bash -c "cd /workspace/qlib_workspace && python factor.py"
bash $QUANT_SKILL_DIR/scripts/run_quant_round.sh "$ROUND_DIR" factor

# ── 模型轮 ──
mkdir -p "$ROUND_DIR/{model_name}"
# Agent 写 model.py + model_meta.json ...
$PYTHON_BIN "$MODEL_SKILL_DIR/scripts/validate_model.py" "$ROUND_DIR/{model_name}"
bash $QUANT_SKILL_DIR/scripts/run_quant_round.sh "$ROUND_DIR" model

# ── 通用: 查看 Bandit 建议 ──
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/action_advisor.py suggest --exp-root $QUANT_EXP_ROOT

# ── 通用: 查看历史 ──
$PYTHON_BIN $QUANT_SKILL_DIR/scripts/quant_trace.py show --exp-root $QUANT_EXP_ROOT
```

---

## 数据流转

```
用户: "优化量化策略"
  → Agent: 环境初始化 → 工作区初始化
  → Bandit 建议 + 用户选方向

  ┌─ 因子循环 ─────────────────────────────────────────┐
  │ 1. CoSTEER: 读 quant_trace.json + error_knowledge  │
  │ 2. 设计因子方案 → 用户确认                           │
  │ 3. 写 factor.py → 验证 → Docker 全量执行             │
  │ 4. 交叉集成: SOTA 模型自动注入（可选评估）            │
  │ 5. 回测 → 分析 → SOTA 更新 → 记录 trace             │
  │ 6. 展示结果 + Bandit 建议                           │
  │    "继续因子 / 切模型 / 停止?"                       │
  └────────────────────────────────────────────────────┘
        ↕ 切换时 SOTA 因子/模型自动交叉传递
  ┌─ 模型循环 ─────────────────────────────────────────┐
  │ 1. CoSTEER: 读 quant_trace.json + error_knowledge  │
  │ 2. 设计模型方案 → 用户确认                           │
  │ 3. 写 model.py → 验证                              │
  │ 4. 交叉集成: SOTA 因子自动注入模型训练!              │
  │ 5. 回测 → 分析 → SOTA 更新 → 记录 trace             │
  │ 6. 展示结果 + Bandit 建议                           │
  │    "继续模型 / 切因子 / 停止?"                       │
  └────────────────────────────────────────────────────┘
```

---

## 配置体系

所有参数统一在 `.env` 中。因子轮和模型轮共享相同的日期区间、市场、策略参数。

**因子专属参数**: `learning_rate`, `max_depth`, `num_leaves` 等 (LightGBM)
**模型专属参数**: `n_epochs`, `lr`, `early_stop`, `batch_size`, `weight_decay` 等 (PyTorch)

---

## 错误处理

统一使用 fin-factor 的 `collect_error.py`，错误知识库存储在 `$QUANT_EXP_ROOT/error_knowledge.jsonl`。

```bash
# 记录错误
$PYTHON_BIN "$SKILL_DIR/scripts/collect_error.py" record \
    --exp-root "$QUANT_EXP_ROOT" --round $ROUND \
    --stage validate --error "错误信息"

# 标注根因
$PYTHON_BIN "$SKILL_DIR/scripts/collect_error.py" annotate \
    --exp-root "$QUANT_EXP_ROOT" --id err_xxx \
    --root-cause "原因" --fix "修复方法" --fixed

# 查看摘要（每轮必做）
$PYTHON_BIN "$SKILL_DIR/scripts/collect_error.py" summary \
    --exp-root "$QUANT_EXP_ROOT" --round $ROUND
```

---

## 文件布局

```
$QUANT_EXP_ROOT/
├── daily_pv.h5                       ← 全量数据（因子轮共用）
├── daily_pv_debug.h5                 ← 调试数据（因子快速验证）
├── conf_baseline.yaml                ← 因子基线 (LightGBM)
├── conf_combined_factors.yaml        ← 因子合并 (LightGBM)
├── conf_single_factor.yaml           ← 单因子 (LightGBM)
├── conf_baseline_model.yaml          ← 模型基线 (PyTorch)
├── conf_sota_model.yaml              ← 模型+SOTA因子 (PyTorch)
├── conf_factor_with_sota_model.yaml  ← ★因子+SOTA模型 (PyTorch)
├── quant_trace.json                  ← 统一追踪（全部历史 + Bandit）
├── sota_record.json                  ← 统一 SOTA（因子+模型）
├── sota_combined.parquet             ← SOTA 因子集合
├── current_sota_model.py             ← SOTA 模型代码
├── error_knowledge.jsonl             ← 错误知识库
├── summary.md                        ← 累积实验摘要
├── model_sota/                       ← SOTA model.py 备份
├── round_1/  (action=factor)
│   ├── action.json
│   ├── factor_a/factor.py
│   ├── combined_factors_df.parquet
│   ├── qlib_res.csv
│   └── analysis.json
├── round_2/  (action=factor)
│   └── ...
├── round_3/  (action=model)
│   ├── action.json
│   ├── GRU_v1/model.py
│   ├── combined_factors_df.parquet   ← 自动从 SOTA 因子复制!
│   ├── qlib_res.csv
│   └── analysis.json
└── round_4/  (action=factor)
    └── ...  ← SOTA 模型自动注入评估!
```

---

## 独立性说明

- fin-quant **调用** fin-factor 和 fin-model 的脚本，通过 `$SKILL_DIR` 和 `$MODEL_SKILL_DIR` 路径引用
- fin-factor 和 fin-model **不修改** — 保持向后兼容，独立使用不受影响
- fin-quant 自身只有 **~9 个文件**（全是编排胶水层）

---

## 参考文档

| 文档 | 说明 |
|------|------|
| [feedback-format.md](./references/feedback-format.md) | **结构化反馈格式**（每轮必读） |
| [bandit-guide.md](./references/bandit-guide.md) | Bandit Thompson Sampling 算法 |
| fin-factor references/ | 因子 Specification、代码规范、假设反馈 |
| fin-model references/ | 模型架构指南、代码规范、假设反馈 |

> 📌 **来源**: 本 skill 对标 [RD-Agent QuantRDLoop](../../RD-Agent/rdagent/app/qlib_rd_loop/quant.py)，
> 将其自动化联合优化循环转化为用户主导的交互式 Copilot 技能。
