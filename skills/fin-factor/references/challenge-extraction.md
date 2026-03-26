# 挑战提炼规范 (Challenge Extraction)

本文档定义因子研发中**从实验历史系统性提炼挑战**的规范流程，对标 RD-Agent prompts_v2 中的 `feedback_problem` / `scenario_problem` 机制。

> 📌 **触发时机**：仅在第 2 轮及以后执行（首轮无历史实验）。

---

## 1. 为什么需要挑战提炼

直接从"上轮结果 → 新假设"容易导致：
- 重复尝试失败方向（没系统总结）
- 假设与真实瓶颈脱节（拍脑袋选方向）
- 多轮实验后知识碎片化（散落在 analysis.json / error_knowledge.jsonl 里）

挑战提炼层是"先诊断、再开药"——把碎片信息结构化为可操作的挑战列表，后续假设必须针对其中某个挑战生成。

---

## 2. 挑战分类体系

每个挑战必须归入以下两类之一：

### 2.1 Dataset-Driven Challenge（数据驱动挑战）

主要源于数据本身的结构或统计特性，需要通过数据工程手段解决。

| 典型挑战 | 说明 | 识别信号 |
|---------|------|---------|
| **高 NaN 率** | 因子输出 NaN 占比 > 30%，有效信号被稀释 | `validate_factor.py` 报 NaN 比例告警 |
| **因子共线性** | 新因子与 SOTA 因子库高度相关 | `merge_factors.py` 去重率 > 80%（退出码 2） |
| **数据覆盖不足** | 因子仅对部分股票有效（如仅覆盖大盘股） | 回测中持仓集中度过高 |
| **时序稀疏** | 因子信号频率过低（如每月才有一次触发） | IC 有效但 ICIR 极低 |
| **极端值/厚尾** | 因子值分布偏度过大，少数极端值主导模型 | LightGBM 特征重要性中因子排名波动大 |
| **窗口期不匹配** | 回看窗口太短（噪声大）或太长（滞后严重） | 不同窗口期因子 IC 差异显著 |

### 2.2 Domain-Informed Challenge（领域知识挑战）

主要源于金融领域的特殊约束，需要领域知识介入解决。

| 典型挑战 | 说明 | 识别信号 |
|---------|------|---------|
| **时间泄露 (Lookahead Bias)** | 因子计算使用了未来数据 | IC 异常高（> 0.1）但实盘不可复现 |
| **换手率过高** | 因子信号变化太快导致频繁交易 | 回测中交易成本吃掉大部分收益 |
| **因子衰退 (Decay)** | 因子在训练期有效但测试期失效 | train IC >> test IC（差距 > 0.02） |
| **市值偏差 (Size Bias)** | 因子只在小盘/大盘股有效，非普适 | 持仓中某一市值区间过度集中 |
| **行业集中** | 因子驱动的选股集中在某 1-2 个行业 | 回测最大回撤与行业轮动高度相关 |
| **收益-回撤冲突** | 因子提升收益但同时放大了回撤 | 年化收益 ↑ 但最大回撤 ↑↑ |
| **与基线因子冗余** | 新因子本质上是 Alpha158 的线性变换 | IC 高但合并后无增量（与基线 IC 去重率 > 90%） |

---

## 3. 输入数据源

挑战提炼的输入来自以下文件，Agent 必须在提炼前读取：

| 数据源 | 文件 | 内容 |
|--------|------|------|
| **实验历史摘要** | `$EXP_ROOT/summary.md` | 所有轮次的假设、因子、指标、决策 |
| **错误知识库** | `$EXP_ROOT/error_knowledge.jsonl` | 所有阶段的错误记录（含标注后的 root_cause） |
| **上轮分析** | `$ROUND_DIR/../round_{N-1}/analysis.json` | 最近一轮的指标对比和 SOTA 决策 |
| **SOTA 因子库** | `$EXP_ROOT/sota_combined.parquet` | 已入库的 SOTA 因子列表（用于判断冗余） |

---

## 4. 输出格式

挑战提炼结果存入 `$ROUND_DIR/challenges.json`，格式如下：

```json
{
    "round": 2,
    "extracted_from": {
        "summary_rounds": [1],
        "error_count": 3,
        "last_analysis": "round_1/analysis.json"
    },
    "challenges": [
        {
            "id": "ch_001",
            "type": "dataset_driven",
            "title": "量价因子与 Alpha158 共线性过高",
            "evidence": "第 1 轮 merge_factors.py 去重率 85%，2/3 因子被过滤",
            "severity": "high",
            "suggested_direction": "切换到波动率/分布类因子，降低与基线的线性相关"
        },
        {
            "id": "ch_002",
            "type": "domain_informed",
            "title": "5日动量因子在测试期衰退明显",
            "evidence": "train IC=0.035, test IC=0.012, 差距 0.023 > 阈值 0.02",
            "severity": "medium",
            "suggested_direction": "增大窗口期或加入自适应衰减机制"
        }
    ]
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `id` | string | ✅ | 唯一标识，格式 `ch_NNN`，全局递增 |
| `type` | enum | ✅ | `dataset_driven` 或 `domain_informed` |
| `title` | string | ✅ | 挑战的一句话描述 |
| `evidence` | string | ✅ | 来源证据（引用具体指标/错误/轮次） |
| `severity` | enum | ✅ | `high` / `medium` / `low` |
| `suggested_direction` | string | ✅ | 建议的解决方向（不是具体因子设计） |

### severity 分级标准

- **high**：直接阻碍 SOTA 提升（如全部去重、IC < 0.01）
- **medium**：限制提升空间但不致命（如因子衰退、覆盖率偏低）
- **low**：优化项（如换手率略高、极端值未处理）

---

## 5. 提炼流程

### 5.1 Agent 执行步骤

```
1. 读取 $EXP_ROOT/summary.md — 提取每轮的假设、结果、决策
2. 读取 $EXP_ROOT/error_knowledge.jsonl — 提取未修复 & 已修复的错误模式
3. 读取上轮 analysis.json — 提取最近的指标对比
4. 对照 §2 挑战分类表 — 逐条检查是否匹配
5. 去重 — 如果某个挑战在之前轮次已提炼且已被成功解决，不再重复
6. 排序 — 按 severity（high > medium > low）输出
7. 写入 $ROUND_DIR/challenges.json
```

### 5.2 首轮处理

首轮（第 1 轮）**跳过**挑战提炼，因为没有实验历史。Agent 在第 1 步直接从用户想法出发。

### 5.3 与假设生成的关联

挑战提炼完成后，Agent 在生成假设时**必须**：
1. 明确引用挑战 ID（如"针对 ch_001"）
2. 假设的 `reason` 字段中包含挑战证据
3. 如果忽略某个 high-severity 挑战，必须说明理由

---

## 6. 与其他文档的关联

| 文档 | 关联说明 |
|------|---------|
| [hypothesis-feedback.md](./hypothesis-feedback.md) | 假设生成时引用 challenges.json 中的挑战 ID |
| [rd-agent-specs.md](./rd-agent-specs.md) | 因子渐进策略中的"连续失败换方向"与 high-severity 挑战对应 |
| [metrics-guide.md](./metrics-guide.md) | severity 阈值参考指标判断标准 |
| SKILL.md 第 1.7 步 | 挑战提炼在工作流中的具体位置和命令 |

---

## 7. 示例：从实验历史到挑战

### 输入（summary.md 片段）

```markdown
# 第 1 轮
假设: 5日动量因子可捕捉短期趋势延续
因子: mom5d (IC=0.028)
决策: SOTA_UPDATED（年化 10.5% > 基线 10.1%）

# 第 2 轮
假设: 10日和20日动量因子可捕捉更稳定的趋势信号
因子: mom10d (IC=0.022), mom20d (IC=0.019)
决策: REJECTED — merge 去重过滤了 mom10d（与 mom5d 相关 0.92）
      — mom20d IC < 0.02 无效
```

### 输出（challenges.json）

```json
{
    "round": 3,
    "challenges": [
        {
            "id": "ch_001",
            "type": "dataset_driven",
            "title": "动量因子间高度共线，多窗口变体被去重",
            "evidence": "第 2 轮 mom10d 与 mom5d 相关 0.92，被 merge 过滤",
            "severity": "high",
            "suggested_direction": "停止动量因子变体探索，转向量价或波动率维度"
        },
        {
            "id": "ch_002",
            "type": "domain_informed",
            "title": "长窗口动量因子信号衰退",
            "evidence": "mom20d IC=0.019 < 阈值 0.02，可能反映 A 股市场动量半衰期约 5-10 天",
            "severity": "medium",
            "suggested_direction": "如继续动量维度，考虑加入衰减权重而非简单拉长窗口"
        }
    ]
}
```

> 📖 **假设生成规范**详见 [hypothesis-feedback.md](./hypothesis-feedback.md)
> 📖 **指标判断标准**详见 [metrics-guide.md](./metrics-guide.md)
