---
name: fin-paper-reader
description: '量化论文/研报解读 Agent。读取 PDF、理解思路、提取因子与模型 Specification，衔接 fin-factor / fin-model 进行代码实现与回测。Use when: 读论文、解读研报、论文复刻、paper reading、研报因子提取、论文模型提取。'
argument-hint: '提供 PDF 路径即可，例如："/path/to/paper.pdf"'
---

# 量化论文 / 研报解读 Agent

## 概述

用户提供一篇量化研究论文或券商金工研报的 PDF，Agent 负责：
1. **读取论文** — 提取 PDF 全文文本
2. **理解论文** — 生成结构化摘要，判断论文类型
3. **提取 Specification** — 因子/模型的标准化 JSON 规范
4. **用户确认** — 展示提取结果，用户挑选/修改
5. **衔接下游** — 输出可直接用于 `fin-factor` / `fin-model` 的 Specification

**核心原则**：
- **只做解读，不写实现代码** — 编码和回测交给下游 Skill
- **交互式** — 每步都有用户确认点
- **格式兼容** — 输出严格对齐 `fin-factor` / `fin-model` 的 Specification 格式
- **中英双语** — 支持中文券商研报和英文学术论文

> **来源**: 本 Skill 的论文分析方法改编自 [RD-Agent](../../RD-Agent/) 的论文因子提取管线
> （`rdagent/scenarios/qlib/factor_experiment_loader/pdf_loader.py`），
> 将其自动化批量处理改造为交互式 Copilot 技能。

---

## 前置条件

本 Skill **不需要 Docker 环境**，只需要基本的 Python 依赖：

```bash
pip install pypdf
# 可选：首页截图功能
pip install pymupdf
```

> 💡 本 Skill 只做论文解读和 Specification 提取，不执行代码也不做回测。如果要实现提取的因子/模型，需要先确保 `fin-factor` 或 `fin-model` 的环境已初始化。

---

## 完整工作流程

### Step 1：读取论文

用户提供 PDF 本地路径，Agent 提取全文文本。

```bash
python .github/skills/fin-paper-reader/scripts/read_paper.py "/path/to/paper.pdf" --screenshot
```

**输出**：
- 全文文本（`*_extracted.txt`）
- 基本信息：页数、字符数、语言检测
- 首页截图（可选）

**Agent 操作**：
1. 执行 `read_paper.py` 提取文本
2. 如果文本超过 80000 字符，自动截断（保留首尾）
3. 读取提取的全文文本，进入 Step 2

> ⚠️ **如果 PDF 是扫描件**（提取文本为空或乱码），告知用户需要 OCR 预处理，本 Skill 暂不支持扫描件。

---

### Step 2：理解论文 & 展示摘要 ⏸️ **用户确认点 #1**

Agent 通读全文，生成结构化摘要并展示给用户。

**必须参考**：[paper-analysis-prompts.md](./references/paper-analysis-prompts.md) 中的 Prompt 1（分类）和 Prompt 2（摘要生成）

#### 2.1 论文分类

先判断论文类型：

| 类型 | 说明 | 后续操作 |
|------|------|---------|
| `quantitative_factor` | 以因子研究为主 | 提取因子 Spec |
| `quantitative_model` | 以模型研究为主 | 提取模型 Spec |
| `mixed` | 因子 + 模型都有 | 两者都提取 |
| `irrelevant` | 非量化选股 | 告知用户并终止 |

#### 2.2 展示摘要

使用以下格式展示给用户：

```
📖 论文解读：《论文标题》

📋 基本信息
  来源: [券商/期刊]
  语言: [中文/英文]
  类型: [因子研究 / 模型研究 / 混合]
  页数: [N页]

🎯 核心问题
  [论文试图解决什么问题？]

💡 核心方法
  [主要方法论，2-3句]

📊 关键发现
  1. [发现1]
  2. [发现2]

🔑 可复现要素
  因子: [N 个可提取]
  模型: [N 个可提取]
  数据需求: [日频价量 / 其他]
  复现难度: [低/中/高]

👉 你想提取哪些内容？
  A) 只提取因子（衔接 fin-factor）
  B) 只提取模型（衔接 fin-model）
  C) 因子 + 模型都提取
```

**等待用户确认方向后才继续。**

---

### Step 3：提取 Specification

根据用户选择的方向，逐步提取因子和/或模型的结构化规范。

#### 3.1 因子提取（如适用）

**必须参考**：
- [paper-analysis-prompts.md](./references/paper-analysis-prompts.md) Prompt 3-7
- [factor-extraction-spec.md](./references/factor-extraction-spec.md)

**多轮提取流程**（对标 RD-Agent `pdf_loader.py` 的多轮 LLM 会话）：

**轮次 1：提取因子名称和描述**

逐段阅读论文，提取所有因子：
- 正文中定义的因子
- **表格中出现的因子**（容易遗漏！）
- 附录和对比基线中的因子
- 不同参数变体（5日/10日/20日窗口视为不同因子）

**轮次 2：提取数学公式和变量**

对每个因子：
1. 找到论文中的原始公式
2. 转换为 LaTeX 格式
3. 列出所有变量和函数的含义
4. **映射数据源**：将论文描述映射到 `daily_pv.h5` 的实际字段（`$close`, `$open`, `$high`, `$low`, `$volume`, `$factor`）

> ⚠️ **数据可用性是核心约束**。参见 [factor-extraction-spec.md](./references/factor-extraction-spec.md) 中的数据映射表。依赖不可用数据的因子必须标记为 `not_viable`。

**轮次 3：可行性验证**

逐个检查：
- ✅ 能在日频计算？
- ✅ 能按个股计算？
- ✅ 能用 daily_pv.h5 的 6 个字段实现？
- ✅ 无前向偏差（不需要未来数据）？
- ⚠️ 实现复杂度如何？（低/中/高）

**轮次 4：去重**

检查提取的因子中是否有：
- 名称不同但计算逻辑相同的
- 公式等价但变量命名不同的
- 合并规则：保留公式更完整的版本

#### 3.2 模型提取（如适用）

**必须参考**：
- [paper-analysis-prompts.md](./references/paper-analysis-prompts.md) Prompt 8
- [model-extraction-spec.md](./references/model-extraction-spec.md)

**提取内容**：
1. 模型名称和类型（Tabular / TimeSeries）
2. 逐层架构描述（输入→隐藏→输出）
3. 核心数学公式（LaTeX）
4. 超参数设置
5. 创新点（与传统模型的区别）

**Qlib 适配检查**：
- 输出必须是 `(batch, 1)` — 单值预测
- 参数量建议 <50K — 避免过拟合
- 不能自定义训练循环 — Qlib 框架负责
- 签名必须是 `__init__(self, num_features, num_timesteps=None)`

---

### Step 4：用户确认 & 优化 ⏸️ **用户确认点 #2**

展示提取结果，让用户挑选和修改。

#### 4.1 因子展示（如适用）

```
📋 从论文中提取了 N 个因子：

| # | 因子名 | 类型 | 描述 | 难度 | 可行? |
|---|--------|------|------|------|-------|
| 1 | VMM_5 | 量价 | 5日成交量加权动量 | 🟢低 | ✅ |
| 2 | VOL_20 | 波动率 | 20日对数收益率标准差 | 🟢低 | ✅ |
| 3 | HF_skew | 高频 | 日内收益率偏度 | 🔴高 | ❌ 需分钟数据 |

详细 Specification:

  VMM_5:
    描述: [量价因子] 5日成交量加权动量
    公式: $VMM\_5 = \sum_{i=1}^{5} w_i \times R_{t-i}$
    变量: w_i = 成交量权重, R_{t-i} = 日收益率
    数据: $close, $volume
    难度: 🟢低

  VOL_20:
    描述: [波动率因子] 20日对数收益率标准差
    公式: $VOL\_20 = \text{std}(\ln(C_{t-i}/C_{t-i-1}), i=1..20)$
    变量: C_{t-i} = 收盘价
    数据: $close
    难度: 🟢低

👉 请确认：
  1. 要实现哪些因子？（输入序号，如 "1,2"）
  2. 需要修改描述或公式吗？
  3. 有其他因子想补充吗？
```

#### 4.2 模型展示（如适用）

```
📐 从论文中提取了 N 个模型：

| # | 模型名 | 类型 | 描述 | 难度 |
|---|--------|------|------|------|
| 1 | ALSTM | TimeSeries | LSTM + Temporal Attention | 🟡中 |

详细 Specification:

  ALSTM:
    描述: Attention-based LSTM for stock return prediction
    架构: Input(B,T,F) → LSTM(F,64,layers=2) → Attention(64) → Linear(64,1)
    超参: hidden_dim=64, num_layers=2, dropout=0.1
    训练: epochs=100, lr=2e-4, early_stop=10
    类型: TimeSeries
    参数量估算: ~40K

👉 请确认：
  1. 要实现哪个模型？
  2. 超参需要调整吗？
```

**等待用户确认后才进入 Step 5。**

#### 4.3 保存确认后的 Specification

将最终确认的 Specification 保存为文件：

```bash
# 建议保存到工作空间（如果已有 fin-factor/fin-model 工作区）
mkdir -p "$EXP_ROOT/paper_spec"
# Agent 写入:
#   factor_spec.json   — 因子 Specification
#   model_spec.json    — 模型 Specification
#   source_info.json   — 论文元信息
#   paper_summary.md   — 结构化摘要
```

---

### Step 5：衔接下游 Skill

**必须参考**：[handoff-guide.md](./references/handoff-guide.md)

根据提取内容，输出衔接指引：

#### 5.1 因子衔接

```
✅ 因子 Specification 已生成！

📋 提取了 N 个可实现因子：[factor_1, factor_2, ...]

💡 假设：
  "基于论文《XX》的核心发现，XX因子预期能捕捉XX效应..."

👉 下一步：
  使用 @fin-factor 并告诉它：
  "按照以下 Specification 实现因子，假设来源于论文《XX》"
  [贴出 factor_spec.json 内容]

  fin-factor 会从 Step 1.5（Specification 确认）开始，
  跳过 Step 1（理解想法），直接进入编码和回测。
```

#### 5.2 模型衔接

```
✅ 模型 Specification 已生成！

📐 提取了 1 个模型：[model_name]

💡 假设：
  "基于论文《XX》提出的 XX 架构，预期通过 XX 机制改善预测..."

👉 下一步：
  使用 @fin-model 并告诉它：
  "按照以下 Specification 实现模型，来源于论文《XX》"
  [贴出 model_spec.json 内容]

  fin-model 会从阶段 1.3（假设+Spec）开始，
  跳过阶段 1.0（理解方向），直接进入编码和回测。
```

#### 5.3 混合衔接

如果同时提取了因子和模型：

```
📋 从论文中提取了 N 个因子 + M 个模型。

建议执行顺序：
  1️⃣ 先 @fin-factor → 实现因子，建立 SOTA 因子库
  2️⃣ 再 @fin-model → 实现模型，自动使用 SOTA 因子
  
  或者直接 @fin-quant → 联合因子+模型交替优化
```

---

## 单次使用速查

```
用户: "帮我解读这篇论文 /path/to/paper.pdf"

Agent:
  1. python read_paper.py /path/to/paper.pdf --screenshot
  2. 通读全文 → 生成摘要 → 展示给用户
  3. [用户确认方向] → 提取因子/模型 Specification
  4. 展示提取结果 → [用户确认/修改]
  5. 输出最终 Specification + 衔接指引
```

---

## 数据流转

```
用户提供 PDF
  → read_paper.py 提取文本
  → Agent 分类（因子/模型/混合/不相关）
  → Agent 生成结构化摘要 → 展示给用户
  → [用户确认] 提取方向
  → Agent 多轮提取因子名称 + 描述
  → Agent 提取数学公式 + 变量说明
  → Agent 可行性验证（数据是否可用？）
  → Agent 去重
  → Agent 展示完整 Specification → [用户确认/修改]
  → 保存 factor_spec.json / model_spec.json
  → 生成假设文本 + 衔接指引
  → 用户切换到 @fin-factor 或 @fin-model 开始实现
```

---

## RD-Agent 方法论对照

本 Skill 的论文分析方法改编自 RD-Agent，以下是关键对应关系：

| 能力 | RD-Agent 实现 | fin-paper-reader 改编 |
|------|--------------|---------------------|
| PDF 读取 | `document_reader.py` (Langchain) | `read_paper.py` (pypdf，更轻量) |
| 论文分类 | `classify_system` prompt + LLM 投票 | Agent 自行判断（交互式确认） |
| 因子名提取 | `extract_factors_system` 多轮 session | Agent 多轮阅读 + 提取 |
| 公式提取 | `extract_factor_formulation_system` | Agent 提取 + LaTeX 格式化 |
| 可行性验证 | `factor_viability_system` LLM 判断 | Agent 对照数据可用性表 |
| 相关性验证 | `factor_relevance_system` LLM 判断 | Agent 对照排除规则 |
| 去重 | KMeans 嵌入 + `factor_duplicate_system` | Agent 逐对比较 |
| 假设生成 | `factor_from_report.py` 自动生成 | Agent 生成 + 用户确认 |

> **核心差异**：RD-Agent 是全自动管线（API 批量调用 LLM），本 Skill 是 Agent 自身执行分析（交互式、有用户确认点）。

---

## 支持的论文类型

### ✅ 适合

| 类型 | 示例 |
|------|------|
| 中文金工研报 | 中信建投、海通、华泰的因子/模型研报 |
| 英文量化论文 | arXiv/SSRN 上的 Alpha 因子、时序建模论文 |
| 技术分析研究 | 动量、反转、量价关系的研究 |
| 深度学习选股 | LSTM/Transformer/Attention 应用于选股 |

### ❌ 不适合

| 类型 | 原因 |
|------|------|
| 择时策略 | 非选股，超出 Qlib 因子框架 |
| 宏观研究 | 非个股维度 |
| 期权/衍生品 | 数据不可用 |
| 纯文字评论 | 无可复现内容 |

---

## 常见问题

### Q: 论文太长怎么办？

`read_paper.py` 会自动截断超过 80000 字符的文本（保留首尾各一半）。如果截断后丢失关键内容，Agent 可以用 `read_file` 工具直接读取 `*_extracted.txt` 的特定行范围。

### Q: 提取的因子太多怎么办？

按优先级排序推荐分批实现（见 [handoff-guide.md](./references/handoff-guide.md)）：
- 第一批：论文核心因子 + 难度低
- 第二批：辅助因子 + 难度中
- 跳过：难度高或数据不可用

### Q: 论文方法无法直接用 daily_pv.h5 实现怎么办？

1. 如果可以近似替代 → 标注 `approximation` 并说明
2. 如果完全无法替代 → 标注 `not_viable`
3. 聚焦论文中**能**实现的部分，不强行复刻所有内容

### Q: 可以批量处理多篇论文吗？

v1 版本设计为一次处理一篇。如果用户有多篇论文：
1. 逐篇处理，每篇走完 5 步
2. 将不同论文的因子 Specification 合并后一起交给 `fin-factor`
