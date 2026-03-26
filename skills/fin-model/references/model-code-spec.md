# 模型代码规范（强制 + 不可违）

> 来源: RD-Agent `qlib_model_interface` prompt + `model_execute_template_v1.txt`

## 文件: `model.py`

Agent 生成的 `model.py` 必须严格遵循以下接口规范。  
模型代码**只写网络结构**，训练循环由 Qlib `GeneralPTNN` 自动管理。

---

## 接口要求

### 类定义
```python
import torch
import torch.nn as nn

class YourModelName(nn.Module):
    def __init__(self, num_features: int, num_timesteps: int = None):
        """
        Args:
            num_features: 输入特征数量（如 Alpha20=20, Alpha158=158）
            num_timesteps: 时序窗口长度（TimeSeries 模型必须接收此参数）
                           Tabular 模型可忽略
        """
        super().__init__()
        # ... 定义层 ...

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: 输入张量
               - TimeSeries: shape (batch_size, num_timesteps, num_features)
               - Tabular:    shape (batch_size, num_features)

        Returns:
            output: shape (batch_size, 1) — 每支股票一个预测值
        """
        # ... 前向传播 ...
        return output  # shape: (batch_size, 1)

# ⚠️ 必须在文件末尾定义此全局变量
model_cls = YourModelName
```

### 关键约束

| 规则 | 说明 |
|------|------|
| `model_cls` 必须存在 | Qlib `GeneralPTNN` 通过 `pt_model_uri: "model.model_cls"` 引用 |
| 输出 shape `(batch, 1)` | 多输出会导致 Qlib 回测失败 |
| 不写训练循环 | 由 `GeneralPTNN` 管理（optimizer, loss, early stopping） |
| 不写数据加载 | 由 Qlib `DataHandlerLP` + `Alpha158DL` 管理 |
| 不做特征处理 | 由 Qlib `RobustZScoreNorm` + `Fillna` 管理 |
| 不 `import qlib` | `model.py` 在 Docker 内作为纯 PyTorch 模块被加载 |

---

## 输入 Shape 说明

### TimeSeries 模型 (dataset_cls=TSDatasetH)
```
输入 x.shape = (batch_size, num_timesteps, num_features)
             = (256,         20,             20)

TSDatasetH 会将每个样本展开为过去 num_timesteps 个交易日的特征矩阵。
forward() 需要处理 3D 输入并输出 (batch_size, 1)。
```

### Tabular 模型 (dataset_cls=DatasetH)
```
输入 x.shape = (batch_size, num_features)
             = (256,         20)

DatasetH 每个样本是当日的特征向量。
forward() 处理 2D 输入并输出 (batch_size, 1)。
```

---

## model_meta.json（与 model.py 同目录，必须生成）

```json
{
  "model_name": "GRU_v1",
  "model_type": "TimeSeries",
  "description": "2层 GRU + 全连接输出层",
  "architecture": "GRU(input=20, hidden=64, layers=2, dropout=0.3) → FC(64, 1)",
  "hyperparameters": {
    "hidden_dim": 64,
    "num_layers": 2,
    "dropout": 0.3
  },
  "training_hyperparameters": {
    "n_epochs": 100,
    "lr": 0.0002,
    "early_stop": 10,
    "batch_size": 256,
    "weight_decay": 0.0001
  }
}
```

`model_type` 必须是 `"TimeSeries"` 或 `"Tabular"` 之一，决定：
- YAML 模板中 `dataset_cls` 的选择
- `validate_model.py` 的输入构造方式
- `num_timesteps` 环境变量是否传递

---

## 禁止事项

1. ❌ **不写 `if __name__ == "__main__"`** — model.py 不是入口脚本
2. ❌ **不 `import pandas`** — 模型代码不需要数据处理库
3. ❌ **不写 `torch.save()` / `torch.load()`** — 由 Qlib 管理
4. ❌ **不使用 `sklearn`** — 纯 PyTorch 模型
5. ❌ **不硬编码维度** — 使用 `num_features` 和 `num_timesteps` 参数

---

## 鲁棒性建议

- **Dropout**: 推荐 0.1-0.5，防止过拟合
- **BatchNorm / LayerNorm**: 推荐在全连接层后使用
- **权重初始化**: PyTorch 默认初始化通常足够
- **输出层**: 最后用 `nn.Linear(hidden, 1)` 输出标量预测
- **激活函数**: ReLU / GELU / Tanh 均可，避免 Sigmoid（不适合回归）
