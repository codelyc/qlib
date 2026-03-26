# fin-factor 的 RD-Agent 规范 (Specification)

本文档源自 RD-Agent 规范单元 (Specification Unit) 的核心理念，并专门针对 Qlib 金融因子 (fin-factor) 研发工作流进行了适配。Agent 在设计和实现量化因子时，**必须**严格遵循本规范。

> **RD-Agent 背景**：RD-Agent 是微软开源的自动化研发框架，其核心思想是将研发过程拆分为 **假设生成 → 规范设计 → 代码实现 → 评估反馈** 的闭环。本文档将这一理念适配到 Qlib 因子研发场景。

---

## 1. 核心工作流原则 (Workflow Principles — 规范驱动开发)

在编写任何实现代码之前，Agent **必须**先输出一份纯 Markdown 格式的接口规范 (Specification)，用于定义因子的接口、形状约束和数据假设。

- **在规范设计阶段，绝对不要编写任何实现代码。**
- 规范中必须包含：函数签名定义、详细的 Docstring（包括目的说明、参数、返回值、可能抛出的异常）以及输入输出的形状/维度断言。
- 只有在用户（或系统）确认规范无误后，才允许进入 Python 代码编写阶段。

### 1.1 因子实验输出格式 (Factor Experiment Output Format)

每轮因子设计方案必须以结构化格式输出。对标 RD-Agent 的 `factor_experiment_output_format`，每个因子必须包含以下字段：

```json
{
    "factor_name": {
        "description": "因子描述，以类型标签开头，如 [动量因子]",
        "formulation": "因子的数学公式（LaTeX 格式）",
        "variables": {
            "变量名1": "变量或函数的含义说明",
            "变量名2": "变量或函数的含义说明"
        }
    }
}
```

**示例**：

```json
{
    "vol_ratio5d": {
        "description": "[量价因子] 5日成交量方向比率，衡量近5日买入压力与卖出压力的对比",
        "formulation": "\\text{Vol\\_Ratio} = \\frac{\\sum_{i=1}^{5} \\text{sign}(\\Delta Close_i) \\times Volume_i}{\\sum_{i=1}^{5} Volume_i}",
        "variables": {
            "ΔClose_i": "第 i 天收盘价变动 = Close_i - Close_{i-1}",
            "Volume_i": "第 i 天成交量",
            "sign()": "符号函数，上涨=+1，下跌=-1，不变=0"
        }
    }
}
```

> ⚠️ **所有超参数必须显式声明**。例如窗口期、回看天数等。"10日动量"和"20日动量"必须作为两个独立因子定义。

---

## 2. 假设生成与因子渐进策略 (Hypothesis & Factor Progression)

对标 RD-Agent 的 `factor_hypothesis_specification`，因子研发必须遵循以下渐进策略：

### 2.1 假设驱动

每轮研发前，Agent 必须先形成一个**可验证的假设**，而非随机尝试。假设格式：

```json
{
    "hypothesis": "精确、可验证的陈述，说明为什么此因子预期有效。2-3句话。",
    "reason": "基于已有实验反馈或领域知识的逻辑推导。1-2句话。"
}
```

### 2.2 因子渐进策略（5 条规则）

1. **每轮 1-5 个因子**：平衡简单与复杂，逐步建设因子库。充分利用提供的金融数据（`$open`, `$close`, `$high`, `$low`, `$volume`, `$factor`），不要只盯着某个字段。
2. **简单有效优先**：先从简单、容易实现、大概率有效的因子开始，简要说明为什么预期有效。避免一开始就做复杂组合因子。
3. **渐进增加复杂度**：随着实验积累，逐步引入更复杂的因子（多窗口期、非线性变换、多字段交叉等）。只有简单因子验证后才组合。
4. **连续失败则换方向**：如果多轮连续迭代都未能超越 SOTA，**必须**切换到全新的因子方向，可以从简单因子重新开始。
5. **已入库因子不重复实现**：超越 SOTA 的因子已经自动纳入因子库（`sota_combined.parquet`），每次回测都会自动包含它们。不要重新实现已入库的因子。

### 2.3 挑战驱动的假设生成 (Challenge-Driven Hypothesis)

对标 RD-Agent prompts_v2 的 `feedback_problem` / `scenario_problem` 机制。从第 2 轮起，因子假设**不再凭空生成**，而是基于结构化挑战列表。

**流程**：
1. 从实验历史中提炼挑战（Dataset-Driven 或 Domain-Informed）
2. 假设必须引用至少一个挑战 ID（如"针对 ch_001"）
3. high-severity 挑战优先处理；若忽略，必须说明理由

**假设质量保障**：
- 每个假设必须经过 **5 维打分**（对齐度/预期影响/新颖性/可行性/风险收益）
- 总分 < 25 禁止执行，必须重写
- 打分后进入 **Critique → Rewrite** 精炼循环

> 📖 挑战分类体系和输出格式详见 [challenge-extraction.md](./challenge-extraction.md)
> 📖 5 维打分和 Critique/Rewrite 规范详见 [hypothesis-feedback.md](./hypothesis-feedback.md) §1.3-1.4

---

## 3. 特征工程规范 (Feature Engineering Specification — 因子逻辑)

在设计因子（相当于 RD-Agent 中的 FeatureEng 特征工程阶段）时，必须遵守以下严格约束：

- **禁止未来函数 / 防止时间泄露 (No Lookahead Bias):** 因子的核心是基于历史预测未来。绝对不要在 $t$ 时刻使用 $t+n$ ($n>0$) 的数据。在 Pandas 中使用 `shift(n)` 时，$n$ 必须始终大于 0。
- **形状一致性 (Shape Consistency):** 输出样本的形状（索引长度和层级）必须与规定的输入索引完全匹配。不要在计算过程中隐式地 `drop`（删除）行，这会破坏 Qlib 要求的 `(datetime, instrument)` MultiIndex 结构。
- **鲁棒性 (Robustness — 处理 NaN 和无穷大):**
  - **处理除零错误:** 当涉及除法时，必须在分母上加上一个极小值 (epsilon，例如 `1e-8`)。
  - **处理缺失值:** 合理使用 `fillna()` 或 `dropna()`。但需极其警惕：过度使用 `dropna()` 可能导致最终输出为空表。在进行 `rolling` 窗口操作时，请务必设置合理的 `min_periods` 参数。
  - **处理无穷大:** 对 `np.inf` / `-np.inf` 做 `replace([np.inf, -np.inf], np.nan)` 清洗。
- **模型无关性 (Model-Agnostic):** 因子特征计算逻辑必须独立存在，不得耦合任何下游的机器学习模型代码。

---

## 4. 数据加载规范 (Data Loading Specification — 输入约束)

- **数据源:** 必须且只能从 `daily_pv.h5` 文件中读取数据，对应的 key 必须为 `data`。
- **输入格式:** 载入的原始 DataFrame 带有 `MultiIndex(instrument, datetime)`。
- **可用字段限制:** 只能使用文件内包含的列：`$open`, `$close`, `$high`, `$low`, `$volume`, `$factor` (复权因子)。
- **数据转换:** 通常需要使用 `unstack` 操作将长表转为宽表 (例如 `df['$close'].unstack(level='instrument')`)，以便进行截面(cross-sectional)或时序(time-series)的向量化计算，并在计算完成后再转回长表 (restack)。

---

## 5. 数据处理注释规范 (Data Processing Comment Convention)

对标 RD-Agent 的 `qlib_factor_strategy`，**因子代码中每一步数据转换操作都必须附带注释，明确说明当前数据结构**（索引类型、列名、形状）。

示例：

```python
# 1. 读取数据 — MultiIndex(instrument, datetime), 列: $open, $close, $high, $low, $volume, $factor
df = pd.read_hdf("daily_pv.h5", key="data")

# 2. 透视为宽表 — 行: datetime, 列: instrument（每列一只股票的收盘价）
#    shape: (n_days, n_stocks)
close = df['$close'].unstack(level='instrument').sort_index()

# 3. 计算收益率 — shape 不变: (n_days, n_stocks)，首行为 NaN
daily_ret = close.pct_change(1)

# 4. 滚动窗口计算 — shape 不变: (n_days, n_stocks)，前 window-1 行为 NaN
factor_values = daily_ret.rolling(window=20, min_periods=15).std()

# 5. 转回长表 — MultiIndex(datetime, instrument), 单列 Series
#    注意：stack 后索引顺序自动变为 (datetime, instrument)
result = factor_values.stack()
result.index.names = ['datetime', 'instrument']
```

> 🔑 **核心要求**：读者只看注释就能理解每一步的数据结构变化，无需运行代码。

---

## 6. Qlib 调用规范 (Qlib Invocation Specification — 输出约束)

为确保最终生成的因子能被 Qlib 无缝载入并用于回测，必须满足以下输出要求：

- **数据类型 (Data Type):** 最终的因子值列必须强制转换为 `float64` 类型 (`astype('float64')`)。
- **索引 (Index):** 输出的 DataFrame 必须转换回 `MultiIndex`，且级别名称必须完全精确匹配：`['datetime', 'instrument']`。（请特别注意顺序：时间在前、股票代码在后，这与载入时的原始顺序相反）。
- **列名 (Column Name):** 输出的 DataFrame 必须仅包含**单独一列**，且列名应具有描述性，反映因子本身的名称。
- **持久化存储 (Storage):** 结果必须保存到 `result.h5` 文件中，且 key 必须为 `data`。
- **自我验证 (Validation):** 在脚本退出前，代码必须打印出必要的诊断信息，至少包括：结果表格的 `.shape`、非空数据的数量 (`non-null count`) 以及头部数据 (`.head()`)。

---

## 7. 因子模拟器背景 (Factor Simulation Pipeline)

对标 RD-Agent 的 `qlib_factor_simulator`，理解因子如何被 Qlib 使用至关重要：

1. **因子表生成**：你的 `factor.py` 输出的 `result.h5` 会被 `merge_factors.py` 合并成 `combined_factors_df.parquet`，通过 `StaticDataLoader` 加载到 Qlib 数据集。
2. **模型训练**：Qlib 使用 LightGBM（或其他模型）基于 **Alpha158 基础特征 + 你的新因子** 来预测未来数日收益率。你的因子是模型输入特征的一部分。
3. **组合构建**：基于模型预测的收益率排名，`TopkDropoutStrategy` 选出前 `topk` 只股票构建投资组合。
4. **绩效评估**：回测框架计算 IC、ICIR、年化收益、夏普比率、最大回撤等指标，用于判断因子贡献。

> 💡 **关键认知**：你的因子不是直接用来选股的，而是作为机器学习模型的**输入特征**。好的因子应该为模型提供**额外的预测信息**（与 Alpha158 互补），而非重复已有信息。

---

## 8. 错误知识库与经验积累 (Error Knowledge Base — CoSTEER 启发)

借鉴 RD-Agent CoSTEER 的 `working_trace_error_analysis` 机制，fin-factor 实现了简化版的错误知识库：

### 8.1 核心思路

- **自动采集**：脚本失败时自动记录错误到 `error_knowledge.jsonl`
- **Agent 标注**：Agent 定位根因后补充 `root_cause` + `fix`
- **下轮注入**：每轮开始前读取历史错误摘要，避免重复犯错

### 8.2 与 RD-Agent 的对比

| 能力 | RD-Agent CoSTEER | fin-factor 简化版 |
|------|-----------------|------------------|
| 错误记录 | 自动 (FactorEvaluator) | 自动 (`collect_error.py record`) |
| 相似错误检索 | Embedding RAG (V2) | 关键词匹配 (`collect_error.py summary`) |
| 历史 trace 注入 | 最近 N 轮失败历史 + token 截断 | 全量摘要注入 |
| 成功模式学习 | 知识库存储成功实现用于相似任务 | SOTA 因子库 (`sota_combined.parquet`) |

> 📖 **进阶参考**：如需了解 RD-Agent 完整的 CoSTEER 知识管理机制（V1/V2 RAG 策略、相似错误向量检索、token-aware 截断），可查阅 `RD-Agent/rdagent/components/coder/CoSTEER/knowledge_management.py`。

---

## 9. 模型假设扩展入口 (Model Hypothesis — 可选)

RD-Agent 支持 **factor + model 双轮驱动**：当因子优化遇到瓶颈时，可以切换到模型架构优化。fin-factor 当前专注于因子研发维度，模型部分使用 Qlib 内置的 LightGBM。

**预留扩展点**：如果未来需要支持模型假设（自定义 PyTorch 模型替代 LightGBM），可参考 RD-Agent 的 `model_hypothesis_specification` 和 `qlib_model_interface`，扩展为：

- 在假设中增加 `"action": "factor"` 或 `"action": "model"` 字段
- 模型代码遵循 `class XXXModel(torch.nn.Module)` + `model_cls = XXXModel` 接口
- 回测配置切换为自定义模型 YAML

> ℹ️ 当前阶段无需实现，仅作为架构预留说明。
