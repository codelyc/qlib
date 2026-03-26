#!/usr/bin/env python3
"""
Quant Trace — 统一实验追踪（因子 + 模型完整轨迹）。

对标 CoSTEER 的 working_trace_knowledge + RD-Agent QuantTrace:
  - 记录每轮的 action、任务描述、代码路径、指标、结构化反馈、concise_knowledge
  - 成功和失败都记录（供 Agent 读取时检索经验）
  - 智能过滤: show --focus factor 时只展示因子轮 + 最近一个 SOTA 模型轮（减少噪音）
  - concise_knowledge: 每轮提炼 1-2 句核心洞察，供下一轮参考

用法:
    python quant_trace.py record --exp-root /path --round 1 --action factor \\
        --task "大跌放量反弹因子" --code-path "round_1/vol_rebound/factor.py" \\
        --result success --metrics '{"ic":0.04}' \\
        --feedback '{"observations":"IC不错","hypothesis_evaluation":"验证了动量假设",...}' \\
        --concise-knowledge "5日动量因子IC稳定但换手偏高，需加平滑"

    python quant_trace.py show --exp-root /path
    python quant_trace.py show --exp-root /path --focus factor   # 智能过滤
    python quant_trace.py show --exp-root /path --action factor  # 简单过滤
    python quant_trace.py context --exp-root /path --focus model  # LLM context JSON
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_trace(exp_root: Path) -> dict:
    trace_file = exp_root / "quant_trace.json"
    if trace_file.exists():
        return json.loads(trace_file.read_text())
    return {"rounds": [], "bandit_state": {}}


def save_trace(exp_root: Path, trace: dict):
    trace_file = exp_root / "quant_trace.json"
    trace_file.write_text(json.dumps(trace, indent=2, ensure_ascii=False))


# ═══════════════════════════════════════════════════════════════
# 智能过滤 (参考 RD-Agent quant_proposal.py prepare_context)
# ═══════════════════════════════════════════════════════════════
def filter_rounds_smart(rounds: list, focus_action: str) -> list:
    """智能过滤: 保留所有 focus_action 轮 + 最近一个另一类型 SOTA 轮.

    RD-Agent 设计思想:
      - 做因子时: Agent 应该看到所有因子历史 + 最近一个成功的模型轮（提供模型上下文）
      - 做模型时: Agent 应该看到所有模型历史 + 最近一个成功的因子轮（提供因子上下文）
    这样 Agent 不会被无关历史淹没，同时保留交叉上下文。
    """
    other_action = "model" if focus_action == "factor" else "factor"
    same_action_rounds = []
    best_other_round = None

    for r in rounds:
        if r.get("action") == focus_action:
            same_action_rounds.append(r)
        elif r.get("action") == other_action:
            # 找最近一个 SOTA（is_sota=True）轮，没有就取最近一个成功轮
            is_sota = r.get("is_sota", False)
            is_success = r.get("result") == "success"
            if is_sota:
                best_other_round = r
            elif is_success and best_other_round is None:
                best_other_round = r

    # 组合: 所有同类型 + 最佳异类型
    result = list(same_action_rounds)
    if best_other_round:
        result.append(best_other_round)
    # 按 round 号排序
    result.sort(key=lambda r: r.get("round", 0))
    return result


def cmd_record(args):
    """记录一轮完整轨迹."""
    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)

    metrics = json.loads(args.metrics) if args.metrics else {}

    # 解析结构化反馈 (兼容纯文本和 JSON)
    feedback_raw = args.feedback or ""
    try:
        feedback = json.loads(feedback_raw)
    except (json.JSONDecodeError, TypeError):
        feedback = feedback_raw  # 纯文本 fallback

    entry = {
        "round": args.round,
        "action": args.action,
        "task": args.task or "",
        "code_path": args.code_path or "",
        "result": args.result,  # "success" | "failed" | "partial"
        "metrics": metrics,
        "feedback": feedback,
        "concise_knowledge": args.concise_knowledge or "",
        "is_sota": args.is_sota,
        "timestamp": datetime.now().isoformat(),
    }

    trace.setdefault("rounds", []).append(entry)
    save_trace(exp_root, trace)

    status = "✅" if args.result == "success" else "❌" if args.result == "failed" else "⚠️"
    print(f"{status} 已记录 round {args.round}: action={args.action}, result={args.result}")
    if args.concise_knowledge:
        print(f"   💡 知识: {args.concise_knowledge}")


def cmd_show(args):
    """展示实验历史 (支持智能过滤 --focus)."""
    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)
    rounds = trace.get("rounds", [])

    # 智能过滤 vs 简单过滤
    filter_label = ""
    if args.focus:
        rounds = filter_rounds_smart(rounds, args.focus)
        filter_label = f" [智能过滤: focus={args.focus}]"
    elif args.action:
        rounds = [r for r in rounds if r.get("action") == args.action]
        filter_label = f" [过滤: action={args.action}]"

    if not rounds:
        print(f"暂无实验记录{filter_label}")
        return

    print(f"{'轮次':>4} {'动作':>6} {'结果':>8} {'SOTA':>5} {'任务':<28} {'关键指标'}")
    print("-" * 100)
    for r in rounds:
        metrics = r.get("metrics", {})
        key_metrics = []
        if "ic" in metrics:
            key_metrics.append(f"IC={metrics['ic']:.4f}")
        if "sharpe" in metrics:
            key_metrics.append(f"Sharpe={metrics['sharpe']:.2f}")
        if "arr" in metrics:
            key_metrics.append(f"ARR={metrics['arr']:.2%}")
        metrics_str = ", ".join(key_metrics) if key_metrics else "-"

        task = (r.get("task", "") or "")[:28]
        sota_mark = "★" if r.get("is_sota") else ""
        print(f"{r.get('round', '?'):>4} {r.get('action', '?'):>6} {r.get('result', '?'):>8} {sota_mark:>5} {task:<28} {metrics_str}")

    # 显示 concise_knowledge
    knowledge_entries = [r for r in rounds if r.get("concise_knowledge")]
    if knowledge_entries:
        print(f"\n💡 累积知识:")
        for r in knowledge_entries[-5:]:  # 只显示最近 5 条
            print(f"   R{r['round']}({r['action']}): {r['concise_knowledge']}")

    # 汇总
    all_rounds = trace.get("rounds", [])
    factor_rounds = [r for r in all_rounds if r.get("action") == "factor"]
    model_rounds = [r for r in all_rounds if r.get("action") == "model"]
    print(f"\n📊 汇总: 因子 {len(factor_rounds)} 轮, 模型 {len(model_rounds)} 轮, 共 {len(all_rounds)} 轮{filter_label}")


def cmd_context(args):
    """输出 LLM 决策用的 JSON context (供 action_advisor.py llm-suggest 调用)."""
    exp_root = Path(args.exp_root)
    trace = load_trace(exp_root)
    rounds = trace.get("rounds", [])

    # 智能过滤
    if args.focus:
        filtered = filter_rounds_smart(rounds, args.focus)
    else:
        filtered = rounds

    # 构建精简历史 (只保留 LLM 需要的字段)
    history = []
    for r in filtered:
        entry = {
            "round": r.get("round"),
            "action": r.get("action"),
            "task": r.get("task"),
            "result": r.get("result"),
            "is_sota": r.get("is_sota", False),
            "metrics": r.get("metrics", {}),
        }
        # 结构化反馈: 只保留关键字段
        fb = r.get("feedback", "")
        if isinstance(fb, dict):
            entry["feedback_summary"] = {
                "observations": fb.get("observations", ""),
                "new_hypothesis": fb.get("new_hypothesis", ""),
            }
        elif fb:
            entry["feedback_summary"] = fb
        # concise_knowledge
        if r.get("concise_knowledge"):
            entry["concise_knowledge"] = r["concise_knowledge"]
        history.append(entry)

    # 提取最后一轮详细反馈
    last_round = filtered[-1] if filtered else None
    last_feedback = None
    if last_round:
        fb = last_round.get("feedback", "")
        if isinstance(fb, dict):
            last_feedback = fb
        elif fb:
            last_feedback = {"observations": fb}

    # 累积 concise_knowledge
    all_knowledge = [
        f"R{r['round']}({r['action']}): {r['concise_knowledge']}"
        for r in rounds if r.get("concise_knowledge")
    ]

    context = {
        "total_rounds": len(rounds),
        "factor_rounds": sum(1 for r in rounds if r.get("action") == "factor"),
        "model_rounds": sum(1 for r in rounds if r.get("action") == "model"),
        "filtered_history": history,
        "last_round_feedback": last_feedback,
        "accumulated_knowledge": all_knowledge[-10:],  # 最近 10 条
    }

    print(json.dumps(context, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Quant Trace — 统一实验追踪")
    sub = parser.add_subparsers(dest="cmd")

    # ── record ──
    p_record = sub.add_parser("record", help="记录一轮轨迹")
    p_record.add_argument("--exp-root", required=True)
    p_record.add_argument("--round", type=int, required=True)
    p_record.add_argument("--action", choices=["factor", "model"], required=True)
    p_record.add_argument("--task", default="")
    p_record.add_argument("--code-path", default="")
    p_record.add_argument("--result", choices=["success", "failed", "partial"], required=True)
    p_record.add_argument("--metrics", default="{}")
    p_record.add_argument("--feedback", default="",
                          help="结构化 JSON 或纯文本反馈")
    p_record.add_argument("--concise-knowledge", default="",
                          help="本轮核心洞察 (1-2 句)")
    p_record.add_argument("--is-sota", action="store_true", default=False,
                          help="本轮是否成为新 SOTA")

    # ── show ──
    p_show = sub.add_parser("show", help="展示历史")
    p_show.add_argument("--exp-root", required=True)
    p_show.add_argument("--action", choices=["factor", "model"], default=None,
                        help="简单过滤: 只看指定类型")
    p_show.add_argument("--focus", choices=["factor", "model"], default=None,
                        help="智能过滤: 保留指定类型全部 + 另一类型最佳一轮")

    # ── context ──
    p_ctx = sub.add_parser("context", help="输出 LLM 决策 context JSON")
    p_ctx.add_argument("--exp-root", required=True)
    p_ctx.add_argument("--focus", choices=["factor", "model"], default=None,
                       help="智能过滤方向")

    args = parser.parse_args()
    if args.cmd == "record":
        cmd_record(args)
    elif args.cmd == "show":
        cmd_show(args)
    elif args.cmd == "context":
        cmd_context(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
