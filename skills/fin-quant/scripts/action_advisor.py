#!/usr/bin/env python3
"""
Bandit Action Advisor — 基于 Thompson Sampling 给出"做因子还是模型"的建议。

参考: RD-Agent/rdagent/scenarios/qlib/proposal/bandit.py
      LinearThompsonTwoArm + EnvController

用法:
    python action_advisor.py suggest      --exp-root /path   # Bandit 建议
    python action_advisor.py llm-suggest  --exp-root /path   # LLM 决策 context
    python action_advisor.py record       --exp-root /path --round 3 --action factor --metrics '{...}'

输出 (suggest):
    JSON: {"action":"factor", "scores":{...}, "reason":"...", ...}

输出 (llm-suggest):
    JSON: {"bandit":{...}, "history_summary":"...", "last_feedback":{...}, ...}
    Agent 用此 JSON 作为 context 自行决策（利用 Copilot 的 LLM 能力）

注意: 这只是建议，SKILL.md 会让 Agent 展示给用户，由用户最终决定。
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


# ═══════════════════════════════════════════════════════════════
# 8 维指标向量 (对齐 RD-Agent Metrics)
# ═══════════════════════════════════════════════════════════════
METRIC_KEYS = ["ic", "icir", "rank_ic", "rank_icir", "arr", "ir", "mdd", "sharpe"]

# 指标权重 (对齐 RD-Agent EnvController 默认值)
# [IC, ICIR, Rank_IC, Rank_ICIR, ARR, IR, -MDD, Sharpe]
WEIGHTS = np.array([0.1, 0.1, 0.05, 0.05, 0.25, 0.15, 0.1, 0.2])


def metrics_to_vector(metrics: dict) -> np.ndarray:
    """将指标字典转为 8 维向量 (MDD 取负)."""
    vec = []
    for key in METRIC_KEYS:
        val = float(metrics.get(key, 0.0))
        if key == "mdd":
            val = -abs(val)  # MDD 越小越好，取负使其越大越好
        vec.append(val)
    return np.array(vec)


def compute_reward(metrics: dict) -> float:
    """加权线性奖励."""
    return float(np.dot(WEIGHTS, metrics_to_vector(metrics)))


# ═══════════════════════════════════════════════════════════════
# Linear Thompson Sampling (两臂 Bandit)
# 参考: RD-Agent LinearThompsonTwoArm
# ═══════════════════════════════════════════════════════════════
class ThompsonBandit:
    """简化版 Thompson Sampling for 2 arms: factor vs model."""

    def __init__(self, dim: int = 8, prior_var: float = 10.0, noise_var: float = 0.5):
        self.dim = dim
        self.noise_var = noise_var
        self.arms = {}
        for arm in ("factor", "model"):
            self.arms[arm] = {
                "mean": np.zeros(dim),
                "precision": np.eye(dim) / prior_var,
            }

    def sample_reward(self, arm: str, x: np.ndarray) -> float:
        """从后验分布采样奖励 (Thompson Sampling)."""
        state = self.arms[arm]
        P = state["precision"]
        eps = 1e-6 * np.eye(self.dim)
        try:
            cov = np.linalg.inv(P + eps)
            L = np.linalg.cholesky(cov)
            z = np.random.randn(self.dim)
            w_sample = state["mean"] + L @ z
            return float(np.dot(w_sample, x))
        except np.linalg.LinAlgError:
            # 如果矩阵奇异，返回均值奖励
            return float(np.dot(state["mean"], x))

    def update(self, arm: str, x: np.ndarray, reward: float):
        """Bayesian 线性回归更新."""
        state = self.arms[arm]
        P = state["precision"]
        P_new = P + np.outer(x, x) / self.noise_var
        state["precision"] = P_new
        state["mean"] = np.linalg.solve(
            P_new, P @ state["mean"] + (reward / self.noise_var) * x
        )

    def suggest(self, x: np.ndarray) -> dict:
        """建议下一步 action."""
        scores = {}
        for arm in ("factor", "model"):
            scores[arm] = self.sample_reward(arm, x)
        best = max(scores, key=scores.get)
        return {"action": best, "scores": {k: round(v, 4) for k, v in scores.items()}}

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容 dict."""
        return {
            arm: {
                "mean": state["mean"].tolist(),
                "precision": state["precision"].tolist(),
            }
            for arm, state in self.arms.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ThompsonBandit":
        """从 dict 反序列化."""
        bandit = cls()
        for arm in ("factor", "model"):
            if arm in data:
                bandit.arms[arm]["mean"] = np.array(data[arm]["mean"])
                bandit.arms[arm]["precision"] = np.array(data[arm]["precision"])
        return bandit


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════
def load_trace(exp_root: Path) -> dict:
    trace_file = exp_root / "quant_trace.json"
    if trace_file.exists():
        return json.loads(trace_file.read_text())
    return {"rounds": [], "bandit_state": None}


def save_trace(exp_root: Path, trace: dict):
    trace_file = exp_root / "quant_trace.json"
    trace_file.write_text(json.dumps(trace, indent=2, ensure_ascii=False))


def cmd_suggest(args):
    """给出行动建议."""
    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)
    rounds = trace.get("rounds", [])

    factor_count = sum(1 for r in rounds if r.get("action") == "factor")
    model_count = sum(1 for r in rounds if r.get("action") == "model")

    # 冷启动: 前 2 轮固定 factor，第 3 轮固定 model
    total = len(rounds)
    if total < 2:
        result = {
            "action": "factor",
            "scores": {"factor": 1.0, "model": 0.0},
            "reason": f"冷启动阶段（第{total + 1}轮），先积累因子基线",
            "factor_count": factor_count,
            "model_count": model_count,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if total == 2 and model_count == 0:
        result = {
            "action": "model",
            "scores": {"factor": 0.0, "model": 1.0},
            "reason": "已做2轮因子，建议切换到模型优化（利用已有因子）",
            "factor_count": factor_count,
            "model_count": model_count,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 正常 Bandit 建议
    bandit_state = trace.get("bandit_state")
    if bandit_state and "factor" in bandit_state and "mean" in bandit_state.get("factor", {}):
        bandit = ThompsonBandit.from_dict(bandit_state)
    else:
        bandit = ThompsonBandit()
        # 用历史数据重建 bandit
        for r in rounds:
            if r.get("metrics"):
                x = metrics_to_vector(r["metrics"])
                reward = compute_reward(r["metrics"])
                bandit.update(r["action"], x, reward)

    # 用最近一轮指标作为上下文
    last_metrics = rounds[-1].get("metrics", {}) if rounds else {}
    x = metrics_to_vector(last_metrics) if last_metrics else np.ones(8) * 0.01
    suggestion = bandit.suggest(x)

    # 生成人话解释
    f_score = suggestion["scores"]["factor"]
    m_score = suggestion["scores"]["model"]
    if suggestion["action"] == "factor":
        reason = f"Bandit 采样: 因子({f_score:.2f}) > 模型({m_score:.2f})，建议继续因子优化"
    else:
        reason = f"Bandit 采样: 模型({m_score:.2f}) > 因子({f_score:.2f})，建议切换到模型优化"

    result = {
        "action": suggestion["action"],
        "scores": suggestion["scores"],
        "reason": reason,
        "factor_count": factor_count,
        "model_count": model_count,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_llm_suggest(args):
    """输出 LLM 决策 context — Bandit 建议 + 完整历史摘要 + RAG 提示.

    参考 RD-Agent quant_proposal.py 的 LLM action selection 模式:
    Agent 看到完整上下文后自行决定"做因子还是模型"。
    """
    import subprocess

    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)
    rounds = trace.get("rounds", [])

    # 1. Bandit 建议 (静默调用)
    factor_count = sum(1 for r in rounds if r.get("action") == "factor")
    model_count = sum(1 for r in rounds if r.get("action") == "model")
    total = len(rounds)

    bandit_suggestion = {}
    if total < 2:
        bandit_suggestion = {"action": "factor", "reason": f"冷启动（第{total+1}轮）"}
    elif total == 2 and model_count == 0:
        bandit_suggestion = {"action": "model", "reason": "已做2轮因子，建议切模型"}
    else:
        bandit_state = trace.get("bandit_state")
        if bandit_state and "factor" in bandit_state and "mean" in bandit_state.get("factor", {}):
            bandit = ThompsonBandit.from_dict(bandit_state)
        else:
            bandit = ThompsonBandit()
            for r in rounds:
                if r.get("metrics"):
                    x = metrics_to_vector(r["metrics"])
                    reward = compute_reward(r["metrics"])
                    bandit.update(r["action"], x, reward)
        last_metrics = rounds[-1].get("metrics", {}) if rounds else {}
        x = metrics_to_vector(last_metrics) if last_metrics else np.ones(8) * 0.01
        suggestion = bandit.suggest(x)
        bandit_suggestion = {
            "action": suggestion["action"],
            "scores": suggestion["scores"],
            "reason": f"Bandit 采样: factor={suggestion['scores']['factor']:.2f}, model={suggestion['scores']['model']:.2f}",
        }

    # 2. 历史摘要
    history_lines = []
    for r in rounds:
        m = r.get("metrics", {})
        ic = m.get("ic", "N/A")
        sharpe = m.get("sharpe", "N/A")
        ic_str = f"{ic:.4f}" if isinstance(ic, (int, float)) else str(ic)
        sh_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        is_sota = "★SOTA" if r.get("is_sota") else ""
        history_lines.append(
            f"  R{r.get('round','?')}({r.get('action','?')}): "
            f"result={r.get('result','?')}, IC={ic_str}, Sharpe={sh_str} {is_sota}"
        )

    # 3. 最后一轮反馈
    last_feedback = None
    if rounds:
        fb = rounds[-1].get("feedback", "")
        if isinstance(fb, dict):
            last_feedback = fb
        elif fb:
            last_feedback = {"observations": fb}

    # 4. RAG 动态提示 (参考 RD-Agent quant_proposal.py)
    rag_prompt = ""
    if total < 6:
        rag_prompt = (
            "探索阶段: 尝试简单、快速的因子，覆盖不同视角（动量、反转、量价、波动率）。"
            "模型方面先试 GRU/LSTM 等经典时序模型。"
        )
    else:
        rag_prompt = (
            "深入阶段: 尝试高 IC 因子（多窗口、交叉特征、统计类），避免与 SOTA 重复。"
            "模型方面可尝试更复杂架构（Transformer、Hybrid），但控制模型规模。"
        )

    # 5. concise_knowledge 累积
    knowledge = [
        f"R{r['round']}({r['action']}): {r['concise_knowledge']}"
        for r in rounds if r.get("concise_knowledge")
    ]

    # 6. 组装 context
    context = {
        "bandit_suggestion": bandit_suggestion,
        "experiment_status": {
            "total_rounds": total,
            "factor_rounds": factor_count,
            "model_rounds": model_count,
        },
        "history_summary": "\n".join(history_lines) if history_lines else "无历史记录",
        "last_round_feedback": last_feedback,
        "rag_guidance": rag_prompt,
        "accumulated_knowledge": knowledge[-10:],
        "decision_format": {
            "instruction": "基于以上信息，分析后决定下一轮做 factor 还是 model，给出理由。",
            "output": '{"action": "factor|model", "reasoning": "..."}'
        },
    }

    print(json.dumps(context, ensure_ascii=False, indent=2))


def cmd_record(args):
    """记录一轮结果并更新 Bandit."""
    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)

    metrics = json.loads(args.metrics) if args.metrics else {}

    # 追加轮次记录
    record = {
        "round": args.round,
        "action": args.action,
        "metrics": metrics,
        "reward": compute_reward(metrics) if metrics else 0.0,
    }
    trace.setdefault("rounds", []).append(record)

    # 更新 Bandit 状态
    bandit_state = trace.get("bandit_state")
    if bandit_state and "factor" in bandit_state and "mean" in bandit_state.get("factor", {}):
        bandit = ThompsonBandit.from_dict(bandit_state)
    else:
        bandit = ThompsonBandit()

    if metrics:
        x = metrics_to_vector(metrics)
        reward = compute_reward(metrics)
        bandit.update(args.action, x, reward)

    trace["bandit_state"] = bandit.to_dict()
    save_trace(exp_root, trace)

    print(f"✅ 已记录 round {args.round} (action={args.action}, reward={record['reward']:.4f})")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="Bandit Action Advisor")
    sub = parser.add_subparsers(dest="cmd")

    p_suggest = sub.add_parser("suggest", help="Bandit 行动建议")
    p_suggest.add_argument("--exp-root", required=True, help="工作区路径")

    p_llm = sub.add_parser("llm-suggest", help="LLM 决策 context (Bandit+历史+RAG)")
    p_llm.add_argument("--exp-root", required=True, help="工作区路径")

    p_record = sub.add_parser("record", help="记录一轮结果")
    p_record.add_argument("--exp-root", required=True, help="工作区路径")
    p_record.add_argument("--round", type=int, required=True, help="轮次号")
    p_record.add_argument("--action", choices=["factor", "model"], required=True)
    p_record.add_argument("--metrics", help="JSON 格式指标")

    args = parser.parse_args()
    if args.cmd == "suggest":
        cmd_suggest(args)
    elif args.cmd == "llm-suggest":
        cmd_llm_suggest(args)
    elif args.cmd == "record":
        cmd_record(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
