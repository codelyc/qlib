# 假设-反馈循环规范 (Hypothesis-Feedback Loop)

本文档定义因子研发的**假设生成 → 实验设计 → 反馈分析 → 迭代决策**完整闭环，对标 RD-Agent 的 `hypothesis_and_feedback` + `factor_feedback_generation` 机制。

---

## 1. 假设生成 (Hypothesis Generation)

### 1.1 结构化假设格式

每轮研发前，Agent 必须先形成一个**可验证的假设**。假设不是随机尝试，而是基于已有实验反馈或领域知识的逻辑推导。

**输出格式**（JSON）：

```json
{
    "hypothesis": "精确、可验证、有创新性的陈述。避免过于笼统，确保精确性。假设应明确说明具体方法和预期的绩效改善。2-3句话。",
    "reason": "清晰、有逻辑的解释，说明为什么提出这个假设，基于什么证据（如历史 trace、领域原理等）。1-2句话。"
}
```

**示例**：

```json
{
    "hypothesis": "短期量价背离因子（5日价格上涨但成交量萎缩）可以捕捉趋势衰减信号，为模型提供与 Alpha158 动量因子互补的反转信息，预期 IC 提升 0.01+。",
    "reason": "前两轮纯动量因子 IC=0.028 但与 Alpha158 共线性高（去重率 80%），量价背离从不同维度切入，降低因子冗余。"
}
```

### 1.2 假设来源

| 来源 | 说明 | 适用阶段 |
|------|------|---------|
| **用户想法** | 自然语言描述的直觉或观察 | 首轮 |
| **历史实验反馈** | 上轮 analysis.json 的指标分析 | 后续轮次 |
| **挑战提炼** | `$ROUND_DIR/challenges.json` 中的结构化挑战 | 第 2 轮起 |
| **错误知识库** | `collect_error.py summary` 输出的失败模式 | 每轮 |
| **领域知识** | 量化金融文献、因子研究报告 | 任何时候 |
| **SOTA 差距分析** | 当前结果与 SOTA 的具体差距 | 连续失败时 |

### 1.3 假设自评打分 (Hypothesis Scoring)

对标 RD-Agent prompts_v2 的 5 维假设评估机制。Agent 生成假设后，**必须**对其进行 5 维自评打分（每维 1-10 分），并将打分结果附在假设 JSON 后展示给用户。

**打分维度**：

| 维度 | 打分标准（1=最差, 10=最优） | 关键判断依据 |
|------|---------------------------|-------------|
| **Challenge-Factor Alignment（挑战对齐度）** | 假设是否直接、有效地解决了某个已识别的挑战？ | 引用 `challenges.json` 中的 ID；首轮无挑战时评估与用户需求的对齐度 |
| **Expected IC/Return Impact（预期收益影响）** | 实施成功后，预期对 IC / 年化收益的改善幅度？ | 参考同类因子历史 IC 范围；> 0.03 给 7+，> 0.05 给 9+ |
| **Novelty（新颖性）** | 与历史轮次和 SOTA 因子库中已有因子的差异度？ | 如果是重复尝试（即使换参数）给 1-3；全新维度给 7-10 |
| **Feasibility（实现可行性）** | 因子代码复杂度、数据可得性、执行时间是否合理？ | 简单公式给 8-10；需要复杂滚动窗口/ML 预处理给 4-6 |
| **Risk-Reward（风险收益平衡）** | 考虑失败概率和潜在收益的综合权衡？ | 高确定性低收益 vs 低确定性高收益，平衡最优给 7+ |

**自评输出格式**（追加在假设 JSON 之后）：

```json
{
    "scoring": {
        "challenge_alignment": 8,
        "expected_impact": 6,
        "novelty": 7,
        "feasibility": 9,
        "risk_reward": 7,
        "total": 37
    },
    "scoring_notes": "针对 ch_001（因子共线性），从波动率维度切入，与现有动量因子正交。实现简单（单 rolling 窗口），预期 IC 0.025-0.035。"
}
```

**门槛规则**：
- 总分 ≥ 25 分 → 允许执行
- 总分 < 25 分 → **禁止执行，必须重写假设**（进入 §1.4 Critique & Rewrite）
- 任何单维 ≤ 2 分 → **触发对该维度的针对性重写**

**展示模板（嵌入第 1 步方案展示中）**：

```markdown
> 📊 **假设自评**：
> | 维度 | 得分 |
> |------|------|
> | 挑战对齐 | 8/10 |
> | 预期影响 | 6/10 |
> | 新颖性 | 7/10 |
> | 可行性 | 9/10 |
> | 风险收益 | 7/10 |
> | **合计** | **37/50** ✅ |
```

### 1.4 假设批判与重写 (Hypothesis Critique & Rewrite)

对标 RD-Agent prompts_v2 的 `hypothesis_critique` → `hypothesis_rewrite` 两步精炼机制。Agent 在打分后，**必须**对自己的假设进行一轮自我审视，然后重写为更精确、可执行的版本。

#### Critique 三维度

Agent 必须从以下三个维度审视假设：

1. **可行性审查 (Feasibility Assessment)**
   - 技术风险：实现中是否有重大障碍（如需要不可得的数据字段）？
   - 时间约束：因子计算是否能在合理时间内完成（Docker 全量 < 10min）？
   - 集成风险：与现有 SOTA 因子库合并时是否有冲突（如索引不对齐）？

2. **对齐度审查 (Alignment Check)**
   - 假设是否真正解决了挑战的根因，而非只处理表面症状？
   - 如果是后续轮次：类似方法是否已在历史中尝试过？吸取了什么教训？
   - 预期结果是否可度量（IC/收益/回撤的具体预期值）？

3. **改进方向 (Improvement Direction)**
   - 如果假设过于模糊，指出需要具体化的方法或策略
   - 如果实现有风险，建议降级方案（更简单但更可靠的替代）
   - 如果与历史重复，指出差异点在哪

#### Rewrite 规则

1. **必须具体决定** — 不允许写"试 A 或 B"，必须选定一个方向
2. **不能重述挑战** — Rewrite 后的假设必须比挑战描述更具体、更可执行
3. **不能提备选** — 每条假设只有一个核心行动
4. **保留创新核心** — 不要因为审慎而退回到过于保守的方案
5. **独立可理解** — Rewrite 后的假设不需要阅读原版假设或 Critique 就能理解和执行

#### Critique & Rewrite 输出格式

```json
{
    "critique": {
        "feasibility": "实现简单，仅需 rolling().std()，无技术风险。",
        "alignment": "直接针对 ch_001 的共线性问题，从波动率维度切入与动量正交。但需注意 Alpha158 已有部分波动率因子（如 KLEN），应确认差异性。",
        "improvement": "建议在因子中加入去均值处理（减去截面均值），进一步降低与 Alpha158 波动率因子的相关性。"
    },
    "rewritten_hypothesis": {
        "hypothesis": "截面去均值后的 20 日收益率标准差因子可以捕捉个股相对波动率，与 Alpha158 的绝对波动率因子（KLEN 等）低相关，预期独立 IC > 0.025，合并后可降低因子库整体共线性。",
        "reason": "第 1-2 轮动量因子去重率 85%（ch_001），波动率维度是已知的正交方向；截面去均值进一步保证差异性。"
    }
}
```

#### 执行流程

```
生成假设 → 5维打分
  │
  ├─ 总分 ≥ 25 且无单维 ≤ 2 → Critique → Rewrite → 展示 Rewrite 版本给用户
  ├─ 总分 < 25 → Critique（重点找弱项）→ Rewrite → 重新打分
  │                                                  └─ 仍 < 25 → 换全新假设
  └─ 单维 ≤ 2 → 针对该维度 Critique → Rewrite → 重新打分
```

> ⚠️ **与用户确认的永远是 Rewrite 后的版本**，不是原始假设。

---

## 2. 实验设计 (Experiment Design)

### 2.1 因子列表格式

假设确认后，将假设转化为具体的因子列表。对标 RD-Agent 的 `factor_experiment_output_format`：

```json
{
    "factor_name_1": {
        "description": "[因子类型] 因子描述",
        "formulation": "LaTeX 数学公式",
        "variables": {
            "变量名": "含义说明"
        }
    },
    "factor_name_2": {
        "description": "[因子类型] 因子描述",
        "formulation": "LaTeX 数学公式",
        "variables": {
            "变量名": "含义说明"
        }
    }
}
```

### 2.2 设计约束

- 每轮 **1-5 个因子**，不超过 5 个
- 所有超参数（窗口期、回看天数等）必须在 `formulation` 或 `variables` 中显式声明
- 因子名必须具有描述性（如 `vol_ratio5d`，而非 `factor1`）
- 同一超参数的不同取值算不同因子（如 `mom10d` 和 `mom20d`）

### 2.3 因子执行状态追踪 (Implementation Status)

对标 RD-Agent `factor_feedback_generation` 中 `Factor Implementation: True/False` 的处理。每个因子在实验设计时初始化状态，在执行后更新。

**因子列表扩展格式**（在 §2.1 基础上新增 `implementation_status` 和 `failure_reason` 字段）：

```json
{
    "vol_std20d": {
        "description": "[波动率因子] 20日收益率截面去均值标准差",
        "formulation": "...",
        "variables": { "...": "..." },
        "implementation_status": "success",
        "failure_reason": null
    },
    "vol_skew20d": {
        "description": "[波动率因子] 20日收益率偏度",
        "formulation": "...",
        "variables": { "...": "..." },
        "implementation_status": "failed",
        "failure_reason": "factor.py 执行报错：rolling().skew() 在 min_periods 不足时产出全 NaN"
    }
}
```

**状态枚举**：

| 状态 | 说明 | 后续处理 |
|------|------|----------|
| `success` | 因子成功生成 result.h5 并通过验证 | 参与反馈分析和假设验证 |
| `failed` | factor.py 执行失败或验证未通过 | **不参与假设验证**；自动记入 error_knowledge.jsonl |
| `skipped` | 因合并去重或其他原因被跳过 | **不参与假设验证**；在反馈中标注原因 |

> ⚠️ **关键规则**：`failed` 或 `skipped` 状态的因子**不能用于验证或推翻假设**。如果一轮中所有因子都失败，假设结论为"无法验证"而非"假设不成立"。

---

## 3. 反馈分析 (Feedback Analysis)

### 3.1 结构化反馈格式

每轮回测后，Agent 必须生成结构化反馈。对标 RD-Agent 的 `factor_feedback_generation`：

```json
{
    "observations": "对回测结果的整体观察。包括关键指标变化、与预期的对比。",
    "hypothesis_evaluation": "本轮假设是否被实验支持或推翻，以及具体原因。",
    "decision": "SOTA_UPDATED / KEPT / REJECTED",
    "factor_status_summary": {
        "total": 3,
        "success": 2,
        "failed": 1,
        "skipped": 0,
        "note": "vol_skew20d 执行失败（全 NaN），不参与假设验证。"
    },
    "training_log_analysis": {
        "early_stopping": "未触发，训练完整跑完 100 轮",
        "overfit_signal": "train loss 持续下降，valid loss 在第 60 轮后平稳，无明显过拟合",
        "feature_importance_top5": ["KLEN", "vol_std20d", "ROC5", "RSQR5", "CORR5"],
        "new_factor_rank": "vol_std20d 排名第 2，被模型有效利用"
    },
    "new_hypothesis": "基于本轮结果，建议的下一轮假设方向。",
    "reason": "为什么推荐这个新方向。"
}
```

### 3.2 训练日志分析 (Training Log Analysis)

对标 RD-Agent `last_hypothesis_and_feedback` 中对 `experiment.stdout` 的分析要求。每轮回测后，Agent **必须**分析 LightGBM 训练日志（`$ROUND_DIR/docker_run.log`），判断训练过程是否正常。

**必查项**：

| 检查项 | 日志关键词 | 正常信号 | 异常信号 & 应对 |
|--------|-----------|---------|----------------|
| **Early Stopping** | `early stopping` | 未触发，或在后期触发（> 80 轮） | 前期触发（< 30 轮）→ 学习率过高或数据量不足 |
| **Loss 趋势** | `training's mse`, `valid's mse` | train 下降、valid 平稳或缓降 | valid 上升（过拟合）→ 降 `max_depth`/`num_leaves` |
| **特征重要性** | `feature importance` | 你的新因子出现在前 10 | 新因子不在前 20 → 因子可能无效或被 Alpha158 冗余覆盖 |
| **训练时间** | 总耗时 | < 5 分钟 | > 10 分钟 → 考虑减少因子数或降模型复杂度 |

**训练日志分析输出**（嵌入 §3.1 反馈 JSON 的 `training_log_analysis` 字段）。

> 💡 **特征重要性是关键信号**：如果你的新因子在 LightGBM 特征重要性中排名很低（> 20），说明模型认为它提供的信息不足以辅助预测。这不一定意味着因子无效，但应在反馈中明确记录。

### 3.3 反馈模板（展示给用户）

Agent 在对话中向用户展示反馈时，使用以下模板：

```markdown
## 📊 第 N 轮实验反馈

### 假设验证
> **假设**: [本轮假设（Rewrite 后版本）]
> **结论**: ✅ 假设成立 / ❌ 假设不成立 / ⚠️ 部分成立 / ❓ 无法验证（因子全部失败）

### 因子执行状态
| 因子 | 状态 | 备注 |
|------|------|------|
| factor_a | ✅ success | — |
| factor_b | ❌ failed | rolling().skew() 产出全 NaN |

### 增量归因（合并前诊断）
| 因子 | IC | ICIR | 覆盖率 | 与SOTA相关性 | 判断 |
|------|-----|------|--------|-------------|------|
| factor_a | 0.032 | 0.28 | 95% | 0.35 | 有增量 |
| factor_b | — | — | — | — | 执行失败 |

### 关键指标（三列对比）
| 指标 | 本轮 | Baseline | SOTA | vs Baseline | vs SOTA |
|------|------|----------|------|-------------|---------|
| IC | x.xxx | x.xxx | x.xxx | +x.xxx | +x.xxx |
| ICIR | x.xxx | x.xxx | x.xxx | +x.xxx | +x.xxx |
| 年化收益 | x.x% | x.x% | x.x% | +x.x% | +x.x% |
| 夏普 | x.xx | x.xx | x.xx | +x.xx | +x.xx |
| 最大回撤 | x.x% | x.x% | x.x% | +x.x% | +x.x% |

### 训练日志摘要
| 检查项 | 结果 |
|--------|------|
| Early Stopping | 未触发 / 第 N 轮触发 |
| 过拟合信号 | 无 / train-test IC 差 = x.xx |
| 新因子重要性排名 | 第 N / 未进前 20 |

### SOTA 决策
**结果**: ✅ 已更新 SOTA / ❌ 未更新 / ⚠️ 候选（需用户确认）
**依据**: [综合 4 维评估结论]

### 下一步建议
> [基于反馈 + 挑战提炼的具体建议：深挖 / 换方向 / 微调 / 停止]
```

---

## 4. SOTA 决策树 (SOTA Decision Tree)

对标 RD-Agent `factor_feedback_generation` 中的判断逻辑，以下是精确的 SOTA 更新决策规则：

### 4.0 双基线体系 (Dual-Baseline System)

SOTA 评估需要同时对比**两条基线**，以区分"绝对提升"和"边际提升"：

| 基线 | 文件 | 含义 | 何时生成 |
|------|------|------|----------|
| **静态基线 (Baseline)** | `$EXP_ROOT/baseline_record.json` | 当前 `ACTIVE_FEATURE_SET`（如 ALPHA20）+ 默认 LightGBM，无任何新因子 | `init_workspace.sh` 末尾自动调用 `run_baseline.sh` 生成，后续不变 |
| **动态基线 (Current SOTA)** | `$EXP_ROOT/sota_record.json` | 历史最优结果（含已入库因子） | 每次 SOTA 更新时覆盖 |

**指标对比表**（在 §3.3 反馈模板中增加 Baseline 列）：

```markdown
| 指标 | 本轮 | Baseline | SOTA | vs Baseline | vs SOTA |
|------|------|----------|------|-------------|---------|
| IC | x.xxx | x.xxx | x.xxx | +x.xxx | +x.xxx |
| 年化收益 | x.x% | x.x% | x.x% | +x.x% | +x.x% |
| 最大回撤 | x.x% | x.x% | x.x% | +x.x% | +x.x% |
```

> 📌 如果 `baseline_record.json` 不存在（旧工作空间），Agent 应执行：`bash $SKILL_DIR/scripts/run_baseline.sh $EXP_ROOT` 自动生成。

### 4.0.1 合并前增量归因 (Pre-merge Attribution)

在 merge + backtest **之前**，Agent 应先对每个新因子进行单因子诊断，避免只看合并后总分而无法归因。

**单因子诊断表**（在合并步骤前输出到 `$ROUND_DIR/factor_attribution.json`）：

```json
{
    "round": 2,
    "factors": [
        {
            "name": "vol_std20d",
            "standalone_ic": 0.032,
            "standalone_icir": 0.28,
            "coverage": 0.95,
            "corr_with_sota_top3": {
                "mom5d": 0.12,
                "vol_ratio5d": 0.35,
                "alpha158_KLEN": 0.41
            },
            "verdict": "独立信号强，与 SOTA 相关性可接受，预期有增量"
        },
        {
            "name": "vol_skew20d",
            "standalone_ic": null,
            "standalone_icir": null,
            "coverage": null,
            "corr_with_sota_top3": null,
            "verdict": "执行失败，无法归因"
        }
    ]
}
```

**诊断维度**：
- **standalone_ic**: 单因子 IC（不与其他因子合并）
- **standalone_icir**: 单因子 ICIR
- **coverage**: 非 NaN 覆盖率
- **corr_with_sota_top3**: 与 SOTA 因子库中 IC 最高的 3 个因子的相关系数
- **verdict**: Agent 的综合判断（有增量 / 冗余 / 无效 / 执行失败）

> 💡 **归因先于合并**：先知道每个因子的独立价值，合并回测后才能准确判断"总分提升是谁的功劳"。

### 4.1 更新条件 — 多维综合评估

对标 RD-Agent `auto_sota_selector` 的多维评估机制。更新 SOTA 不再仅看年化收益，需综合 4 个维度：

| 维度 | 权重 | 判断标准 | 来源 |
|------|------|---------|------|
| **年化收益（Primary）** | 最高 | 有任何正向提升即满足 | `analysis.json` |
| **泛化性** | 高 | train IC 与 test IC 的差距 ≤ 0.02 | 训练日志 + 回测指标 |
| **过拟合风险** | 高 | train IC 与 test IC 差距 > 0.02 则标记过拟合警告 | 训练日志 |
| **因子贡献** | 中 | 新因子在 LightGBM 特征重要性中进入前 10 | 训练日志 |

**综合决策规则**：

```
规则 1: 年化收益提升 + 无过拟合警告 + 因子进入前 10
         → ✅ 无条件更新 SOTA

规则 2: 年化收益提升 + 存在过拟合警告（train-test IC 差 > 0.02）
         → ⚠️ 标记为候选，询问用户是否接受（不确定项咨询机制）

规则 3: IC 显著提升（> 0.01）但年化收益微降（< 1%）+ 因子与 SOTA 低相关
         → ✅ 更新（因子多样性有长期价值）

规则 4: 新因子不在特征重要性前 20 + 年化收益无提升
         → ❌ 不更新，因子可能被模型忽略

规则 5: 所有新因子 standalone_ic < 0.02
         → ❌ 不更新，因子本身信号不足
```

### 4.2 不更新但保留观察

```
条件: IC > 0.02 但 ICIR < 0.2
→ 因子有信号但不稳定，不更新 SOTA，但记录为"观察中"
→ 可在后续轮次尝试加 rolling 平滑或更大窗口期
```

### 4.3 换方向信号

```
信号 1: 连续 3 轮 IC < 0.02 → 当前方向已穷尽，必须切换
信号 2: 新因子全部被 IC 去重过滤（merge_factors.py 退出码 2）→ 方向重复
信号 3: 年化收益显著低于 SOTA（> 5% 差距）→ 方向可能有害
```

**Agent 遇到换方向信号时必须**：
1. 在反馈中明确告知用户"当前方向已穷尽"
2. 提出全新的因子方向（不同类型，如从动量类切换到量价关系类）
3. 可以从简单因子重新开始（符合渐进策略规则 4）

### 4.4 决策流程图

```
回测结果出来
  │
  ├─ 年化收益 > SOTA？
  │   ├─ 是 → ✅ 更新 SOTA
  │   └─ 否 → IC 显著提升 > 0.01？
  │       ├─ 是 且 收益降幅 < 1% → ✅ 更新（多样性）
  │       └─ 否 → 连续失败 ≥ 3 轮？
  │           ├─ 是 → 🔄 换方向
  │           └─ 否 → 分析具体原因 → 微调继续
  │
  └─ merge 退出码 = 2？（全部去重）
      └─ 是 → 🔄 因子重复，换方向
```

---

## 5. 历史 Trace 注入 (History Trace Injection)

对标 RD-Agent 的 `hypothesis_and_feedback` 模板，Agent 在每轮决策时应参考完整的实验历史：

### 5.1 Trace 格式

```markdown
=========================================================
# 第 1 轮:
## 假设
[假设内容]
## 因子列表
[因子名称和描述]
## 回测结果
IC: x.xxx | 年化收益: x.x% | 最大回撤: x.x%
## 反馈
观察: [观察] | 假设评估: [评估] | 决策: [SOTA_UPDATED/KEPT/REJECTED]
=========================================================
# 第 2 轮:
...
```

### 5.2 注入时机

- **每轮第 1 步**（理解用户想法）：Agent 内部回顾 `$EXP_ROOT/summary.md` 中的历史
- **每轮第 1.5 步**（设计规范）：对照历史错误 (`collect_error.py summary`) 避坑
- **每轮第 6 步**（反馈）：对比历史趋势判断是否应该换方向

> 💡 **与 RD-Agent 的区别**：RD-Agent 通过 LLM prompt 自动注入最近 N 轮 trace 并做 token 截断。fin-factor 通过 `summary.md` + `analysis.json` 手动管理，Agent 自行读取和综合判断。

---

## 6. 完整闭环示例

### 第 1 轮（首轮）

**假设**:
```json
{
    "hypothesis": "5日成交量方向比率可以捕捉短期资金流向，上涨日放量的股票后续表现更好。",
    "reason": "量价关系是经典的技术分析维度，与 Alpha158 的纯价格因子互补。"
}
```

**实验设计**: 1 个因子 `vol_ratio5d`

**回测结果**: IC=0.031, 年化收益=12.3%（基线 10.1%）

**反馈**:
```json
{
    "observations": "IC=0.031 达到有效因子标准，年化收益较基线提升 2.2%。",
    "hypothesis_evaluation": "假设成立：量价方向比率确实提供了额外预测信息。",
    "decision": "SOTA_UPDATED",
    "new_hypothesis": "在量价维度继续深挖，尝试不同窗口期（10日、20日）和量价背离因子。",
    "reason": "5日窗口有效，更长窗口可能捕捉更稳定的信号。"
}
```

### 第 4 轮（连续失败后换方向）

**假设**:
```json
{
    "hypothesis": "前3轮量价类因子 IC 均 < 0.02，该方向已穷尽。切换到波动率维度：20日收益率偏度可以捕捉尾部风险溢价。",
    "reason": "量价因子与 Alpha158 高度共线（去重率 > 80%），需要全新维度。波动率偏度反映分布不对称性，与已有因子低相关。"
}
```

> 📖 **指标判断标准**详见 [metrics-guide.md](./metrics-guide.md)
> 📖 **报告和汇总模板**详见 [report-templates.md](./report-templates.md)
