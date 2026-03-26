# 下游衔接指南

> 本文档说明 `fin-paper-reader` 的输出如何衔接到 `fin-factor` 和 `fin-model` 的工作流中。

---

## 总览

```
fin-paper-reader（本 Skill）          下游 Skill
─────────────────────────────────     ──────────────

  Step 1: 读取 PDF                
  Step 2: 理解 & 摘要             
  Step 3: 提取 Specification      
  Step 4: 用户确认                
  Step 5: 输出衔接               
       │                          
       ├── 因子 Spec ──────────→  fin-factor Step 1.5（跳过 Step 1 理解阶段）
       │                              → Step 2 写代码
       │                              → Step 3 验证
       │                              → Step 4-6 回测+分析
       │
       └── 模型 Spec ──────────→  fin-model 阶段 1.3（跳过 1.0 理解阶段）
                                       → 阶段 2 编码
                                       → 阶段 3 回测
                                       → 阶段 4 分析
```

---

## 衔接到 fin-factor

### 你的输出

`fin-paper-reader` Step 5 输出的因子 Specification JSON：

```json
{
    "VMM_5": {
        "description": "[量价因子] 5日成交量加权动量",
        "formulation": "VMM\\_5 = \\sum_{i=1}^{5} w_i \\times R_{t-i}",
        "variables": {
            "w_i": "Volume_{t-i} / sum(Volume_{t-1..5})",
            "R_{t-i}": "第 t-i 日收益率"
        }
    },
    "VOL_20": {
        "description": "[波动率因子] 20日对数收益率标准差",
        "formulation": "VOL\\_20 = \\text{std}(\\ln(C_{t-i}/C_{t-i-1}), i=1..20)",
        "variables": {
            "C_{t-i}": "第 t-i 日收盘价"
        }
    }
}
```

### 如何衔接

告诉用户：

```
📋 因子 Specification 已生成！

你可以切换到 fin-factor 来实现这些因子：
  → 使用 @fin-factor 并告诉它：
    "按照以下 Specification 实现因子"
    （附上上面的 JSON）

fin-factor 会从 Step 1.5（Specification 确认）开始，
跳过 Step 1（理解想法），直接进入编码。
```

### fin-factor 接收后的流程

| fin-factor 步骤 | 操作 | 说明 |
|----------------|------|------|
| Step 1 理解想法 | **跳过** | 已由 fin-paper-reader 完成 |
| Step 1.5 Specification | 展示 JSON + 用户确认 | Agent 直接使用提供的 Spec |
| Step 1.6 历史错误 | 正常执行 | 首轮通常为空 |
| Step 1.7 挑战提炼 | 首轮跳过 | — |
| Step 1.8 不确定项 | 如有则询问 | — |
| Step 2 写代码 | 基于 Spec 写 factor.py | 遵循 factor-code-spec.md |
| Step 3+ | 正常流程 | 验证→回测→分析 |

### 假设文本

同时提供假设文本，让 fin-factor 知道研究背景：

```json
{
    "hypothesis": "基于论文《XX》的核心发现，量价动量因子（VMM_5）和波动率因子（VOL_20）预期能捕捉短期量价效应，在 CSI300 上产生正向 IC。",
    "reason": "论文在 2015-2022 样本上验证了这两类因子的有效性，IC 均值分别为 0.04 和 0.03。",
    "source": "《量价因子体系深度研究》, XX证券, 2024"
}
```

---

## 衔接到 fin-model

### 你的输出

`fin-paper-reader` Step 5 输出的模型 Specification JSON：

```json
{
    "ALSTM": {
        "description": "Attention-based LSTM for stock return prediction",
        "formulation": "h_t = LSTM(x_t, h_{t-1}); \\alpha_t = softmax(h_T \\cdot H^T); c = \\sum \\alpha_t h_t; \\hat{y} = W_o c + b",
        "architecture": "Input(B,T,F) → LSTM(F,64,layers=2) → TemporalAttention(64) → Linear(64,1) → Output(B,1)",
        "variables": {
            "h_t": "LSTM hidden state at time t",
            "\\alpha_t": "attention weight for time t",
            "c": "context vector (weighted sum of hidden states)",
            "\\hat{y}": "predicted return"
        },
        "hyperparameters": {
            "hidden_dim": "64",
            "num_layers": "2",
            "dropout": "0.1"
        },
        "training_hyperparameters": {
            "n_epochs": "100",
            "lr": "2e-4",
            "early_stop": "10",
            "batch_size": "256",
            "weight_decay": "1e-4"
        },
        "model_type": "TimeSeries"
    }
}
```

### 如何衔接

告诉用户：

```
📐 模型 Specification 已生成！

你可以切换到 fin-model 来实现这个模型：
  → 使用 @fin-model 并告诉它：
    "按照以下 Specification 实现模型"
    （附上上面的 JSON）

fin-model 会从阶段 1.3（Specification 确认）开始，
跳过阶段 1.0（理解方向），直接进入编码。
```

### fin-model 接收后的流程

| fin-model 阶段 | 操作 | 说明 |
|---------------|------|------|
| 阶段 1.0 理解方向 | **跳过** | 已由 fin-paper-reader 完成 |
| 阶段 1.1 历史错误 | 正常执行 | 首轮通常为空 |
| 阶段 1.2 挑战提炼 | 首轮跳过 | — |
| 阶段 1.3 假设+Spec | 展示 Spec + 用户确认 | Agent 直接使用提供的 Spec |
| 阶段 1.4 不确定项 | 如有则询问 | — |
| 阶段 2.1 写 model.py | 基于 Spec 写代码 | 遵循 model-code-spec.md |
| 阶段 2.2 快速验证 | forward pass <30s | — |
| 阶段 3+ | 正常流程 | 回测→分析 |

---

## 混合场景：因子+模型同时提取

如果论文同时包含因子和模型，输出两份 Specification 并告诉用户：

```
📋 从论文中提取了 3 个因子 + 1 个模型。

建议执行顺序：
1. 先用 @fin-factor 实现因子 → 建立 SOTA 因子库
2. 再用 @fin-model 实现模型 → 使用 SOTA 因子作为输入特征
   （fin-model 的 conf_sota_model.yaml 会自动使用 SOTA 因子）

或者，如果你想联合优化，可以直接使用 @fin-quant 进行因子+模型的交替优化。
```

---

## Specification 文件保存

所有提取的 Specification 保存为文件，方便后续引用：

```
$EXP_ROOT/
├── paper_spec/
│   ├── source_info.json          # 论文元信息（标题、来源、语言）
│   ├── paper_summary.md          # 结构化摘要
│   ├── factor_spec.json          # 因子 Specification（完整）
│   ├── model_spec.json           # 模型 Specification（完整）
│   ├── hypothesis_factor.json    # 因子假设文本
│   ├── hypothesis_model.json     # 模型假设文本
│   └── viability_report.json     # 可行性验证报告
```

---

## 常见问题

### Q: 论文因子依赖的数据不可用怎么办？

将因子标记为 `not_viable`，并告诉用户：
> "该因子需要分钟级数据，当前环境只有日频数据，无法实现。"

如果可以近似替代（如用日频 VWAP 近似分钟级 VWAP），标注 `approximation` 并说明差异。

### Q: 论文模型太复杂（如 GNN、强化学习）怎么办？

标注为 `high_complexity`，并给出简化建议：
> "论文使用 GNN 建模股票关系，但当前环境不支持图数据。建议简化为：保留核心的时序编码器部分（LSTM），去掉图卷积层。"

### Q: 提取的因子太多（>10个）怎么办？

按优先级排序并推荐分批实现：
1. **第一批**（3-5个）：论文核心因子 + 难度低的
2. **第二批**（3-5个）：辅助因子 + 难度中的
3. **跳过**：难度高的或边际收益低的

### Q: 论文的超参设置与 Qlib 环境差异大怎么办？

使用 Qlib 的默认超参作为起点，论文超参仅供参考：
> "论文在 US 市场上使用 lr=1e-4，但 Qlib 的中国市场数据规模较小，建议从 lr=2e-4 开始，如果 early stopping 太早则降低。"
