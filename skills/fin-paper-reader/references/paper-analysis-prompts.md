# 论文分析提示词规范

> 来源：改编自 RD-Agent `factor_experiment_loader/prompts.yaml` 的 7 个核心 Prompt，适配 Copilot Agent 交互式场景。

---

## 设计原则

1. **交互式而非自动化**：RD-Agent 的 Prompt 是面向 LLM API 的批量调用，本规范改编为 Agent 自身的分析思路指引。
2. **中英双语**：支持中文券商研报和英文学术论文。
3. **多轮提取**：因子和模型提取采用多轮迭代，避免遗漏。
4. **结构化输出**：所有输出严格对齐 `fin-factor` 和 `fin-model` 的 Specification 格式。

---

## Prompt 1：论文分类（是否为量化研报）

**用途**：拿到 PDF 文本后，先判断是否值得深入分析。

**Agent 分析维度**：
1. 是否属于金融/量化领域（排除生物、物理等）
2. 是否涉及**选股**（区分于择时、选基）
3. 是否包含**因子构建**或**模型设计**的具体方法
4. 是否有可复现的数学公式或算法描述

**分类结果**：
- `quantitative_factor` — 以因子研究为主（动量、价量、基本面等）
- `quantitative_model` — 以模型研究为主（神经网络、集成学习等）
- `mixed` — 同时包含因子和模型
- `irrelevant` — 不相关（择时、宏观、行业研究等）

**中文研报快速指标**：
- 标题/摘要含 "因子"、"选股"、"量化"、"Alpha"、"特征工程" → 大概率相关
- 标题/摘要含 "择时"、"配置"、"宏观"、"行业" → 大概率不相关
- 有 IC/ICIR/收益率回测表格 → 强相关

**英文论文快速指标**：
- 含 "factor", "alpha", "cross-sectional", "stock selection", "feature engineering" → 大概率相关
- 含 "timing", "macro", "allocation", "bond" → 大概率不相关

---

## Prompt 2：论文摘要生成（RD-Agent 无此步骤，新增）

**用途**：生成结构化摘要展示给用户，让用户确认分析方向。

**Agent 必须提取的信息**：

```markdown
## 论文摘要

### 📖 基本信息
- **标题**: [论文/研报标题]
- **来源**: [券商名/期刊名/arXiv ID]
- **语言**: [中文/英文]
- **类型**: [因子研究 / 模型研究 / 混合]

### 🎯 核心问题
[论文试图解决什么问题？1-2 句话]

### 💡 核心方法
[论文的主要方法论是什么？2-3 句话]

### 📊 关键发现
- [发现1：如 "XX因子在CSI300上IC=0.05"]
- [发现2：如 "GRU模型比LSTM年化收益高2%"]
- [发现3]

### 🔑 可复现要素
- **因子数量**: [N个可提取的因子]
- **模型数量**: [N个可提取的模型]
- **数据需求**: [日频价量 / 分钟级 / 财务数据 / ...]
- **复现难度**: [低/中/高]
```

---

## Prompt 3：因子名称与描述提取

> 改编自 RD-Agent `extract_factors_system`

**Agent 分析指引**（多轮迭代）：

**第 1 轮 — 全面扫描**：
1. 概述论文的主要研究思路
2. 提取**所有**因子，包括：
   - 正文中定义的因子
   - **表格中出现的因子**（容易遗漏！）
   - 附录中的因子
   - 对比基线中的因子
3. 因子名使用英文，不含空格，下划线连接
4. 描述包含：因子类型 + 计算逻辑概述

**第 2+ 轮 — 补充遗漏**：
- 检查是否遗漏了表格中的因子
- 检查是否遗漏了变体因子（如不同窗口期、不同参数）
- 如果没有遗漏则停止

**输出格式**：
```json
{
    "summary": "论文主要研究思路概述",
    "factors": {
        "factor_name_1": "因子描述（含类型+计算逻辑）",
        "factor_name_2": "因子描述"
    },
    "models": {
        "model_name_1": "模型描述（含架构+训练方式）",
        "model_name_2": "模型描述"
    }
}
```

---

## Prompt 4：因子公式提取

> 改编自 RD-Agent `extract_factor_formulation_system`

**Agent 分析指引**：

对每个已提取的因子，从论文中提取：
1. **LaTeX 公式**：变量名不含空格，用下划线连接
2. **变量说明**：每个变量/函数的含义，英文描述

**数据源映射**（关键！将论文中的数据描述映射到实际可用数据）：

| 论文中的表述 | 实际可用数据 | daily_pv.h5 字段 |
|-------------|------------|-----------------|
| 收盘价 / close price | 日频收盘价 | `$close` |
| 开盘价 / open price | 日频开盘价 | `$open` |
| 最高价 / high price | 日频最高价 | `$high` |
| 最低价 / low price | 日频最低价 | `$low` |
| 成交量 / volume | 日频成交量 | `$volume` |
| VWAP | 可用 (open+close+high+low)/4 近似 | 计算字段 |
| 换手率 / turnover | 可用 volume 替代 | `$volume` |
| 复权因子 | 复权因子 | `$factor` |
| 分钟级数据 | ❌ **不可用** | — |
| 财务数据 | ❌ **不可用** | — |
| 一致预期 | ❌ **不可用** | — |

**输出格式**（对齐 fin-factor Specification）：
```json
{
    "factor_name": {
        "formulation": "LaTeX 公式",
        "variables": {
            "variable_1": "变量描述",
            "variable_2": "变量描述"
        }
    }
}
```

⚠️ **如果论文中因子依赖不可用的数据（分钟级、财务数据等），必须标注为 `not_viable` 并说明原因。**

---

## Prompt 5：可行性验证

> 改编自 RD-Agent `factor_viability_system`

**Agent 逐个检查每个因子**：

| 检查项 | 条件 | 不通过则 |
|--------|------|---------|
| **频率** | 能否在日频计算？ | 标记 not_viable |
| **粒度** | 能否按个股计算？ | 标记 not_viable |
| **数据** | 能否用 daily_pv.h5 的 6 个字段实现？ | 标记 not_viable |
| **前向偏差** | 是否需要未来数据？ | 标记 not_viable |
| **复杂度** | 实现难度是否合理？ | 标记 high_complexity |

**输出**：
```json
{
    "factor_name": {
        "viable": true,
        "complexity": "low|medium|high",
        "reason": "可行性说明",
        "data_fields_needed": ["$close", "$volume"]
    }
}
```

---

## Prompt 6：相关性验证

> 改编自 RD-Agent `factor_relevance_system`

**排除的因子类型**：
- 主观判断型（需要人工标注的）
- 自然语言分析型（需要文本数据的）
- 非个股维度的（行业、宏观指标）
- 非日频的（月频、季频因子除非可日频化）

---

## Prompt 7：去重检查

> 改编自 RD-Agent `factor_duplicate_system`

**Agent 逐对比较，合并条件**：
1. 名称不同但计算逻辑完全相同
2. 公式等价（仅变量命名不同）
3. 同一因子的不同窗口期视为**不同因子**（不合并）

**合并策略**：保留公式更完整的版本。

---

## Prompt 8：模型架构提取（新增，RD-Agent 无独立 Prompt）

**Agent 分析指引**：

对论文中的每个模型提取：
1. **模型名称**：英文，简洁
2. **模型类型**：`Tabular` 或 `TimeSeries`
3. **架构描述**：逐层说明（输入层→隐藏层→输出层）
4. **数学公式**：核心计算公式（LaTeX）
5. **超参数**：论文中推荐的超参设置
6. **创新点**：与传统模型的核心区别

**输出格式**（对齐 fin-model Specification）：
```json
{
    "model_name": {
        "description": "模型详细描述",
        "formulation": "核心公式（LaTeX）",
        "architecture": "逐层架构描述",
        "variables": {
            "variable_1": "变量描述"
        },
        "hyperparameters": {
            "hidden_dim": "64",
            "num_layers": "2",
            "dropout": "0.1"
        },
        "training_hyperparameters": {
            "n_epochs": "100",
            "lr": "1e-3",
            "early_stop": "10",
            "batch_size": "256",
            "weight_decay": "1e-4"
        },
        "model_type": "TimeSeries"
    }
}
```

---

## 提取质量检查清单

Agent 完成提取后，必须自检：

- [ ] 论文中**所有**因子都已提取（包括表格中的）？
- [ ] 每个因子都有 description + formulation + variables？
- [ ] 公式中的变量都有对应说明？
- [ ] 数据依赖已映射到 daily_pv.h5 字段？
- [ ] 不可行的因子已标注原因？
- [ ] 无重复因子？
- [ ] 模型架构描述足够详细（能据此写代码）？
- [ ] 超参数有合理默认值？
