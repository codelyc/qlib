#!/usr/bin/env python3
"""
错误知识库管理脚本 — 收集、标注、查询因子研发过程中的错误。
借鉴: rdagent CoSTEER knowledge_management.py working_trace_error_analysis 设计

用法:
  # 脚本失败时自动采集（各脚本失败出口调用）
  python collect_error.py record \\
      --exp-root $EXP_ROOT --round 1 --stage validate \\
      --factor drop_rebound_vol --error "NaN ratio 97%"

  # Agent 标注根因和修复方法（定位后立即调用）
  python collect_error.py annotate \\
      --exp-root $EXP_ROOT --id err_abc123 \\
      --root-cause "close用了未来数据，Ref写反" \\
      --fix "改为 Ref($close,1)/$close - 1" --fixed

  # 新轮次开始前读取历史经验（SKILL.md 要求每轮必调用）
  python collect_error.py summary --exp-root $EXP_ROOT --round 2

  # 按阶段/轮次查询
  python collect_error.py query --exp-root $EXP_ROOT --round 2 --stage validate

  # 列出所有记录
  python collect_error.py list --exp-root $EXP_ROOT

数据格式: $EXP_ROOT/error_knowledge.jsonl（每行一条 JSON）
"""
import argparse
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

KNOWLEDGE_FILE = "error_knowledge.jsonl"

STAGE_LABELS = {
    "validate":    "因子验证 (validate_factor.py)",
    "factor_exec": "Docker 全量执行 (factor.py)",
    "merge":       "因子合并 (merge_factors.py)",
    "backtest":    "Qlib 回测 (run_backtest.sh / qrun)",
    "analyze":     "结果分析 (analyze_results.py)",
    "other":       "其他",
}

# 错误类型自动分类规则
ERROR_TYPE_PATTERNS = [
    ("high_nan",       ["NaN 比例", "nan ratio", "NaN ratio", "null_ratio"]),
    ("zero_variance",  ["方差近 0", "方差接近", "std=", "std <", "零方差", "无区分度"]),
    ("exec_failed",    ["执行失败", "CalledProcessError", "SyntaxError", "NameError",
                        "TypeError", "AttributeError", "ImportError"]),
    ("index_error",    ["MultiIndex", "datetime", "instrument", "IndexError"]),
    ("dedup_all",      ["所有新因子都与 SOTA", "dedup_all", "全部被去重"]),
    ("backtest_error", ["qrun", "LGBModel", "DataHandlerLP", "PortAnaRecord",
                        "exchange", "StaticDataLoader"]),
    ("data_missing",   ["找不到", "不存在", "FileNotFoundError", "No such file", "缺失"]),
    ("timeout",        ["超时", "timeout", "Timeout", "TimeoutExpired"]),
    ("memory_error",   ["OOM", "MemoryError", "killed", "Killed", "内存"]),
    ("format_error",   ["格式", "format", "parquet", "MultiIndex columns", "列名"]),
    ("docker_error",   ["Docker", "docker", "容器", "镜像"]),
]


def classify_error(msg: str) -> str:
    """根据错误信息自动分类"""
    for etype, patterns in ERROR_TYPE_PATTERNS:
        for p in patterns:
            if p.lower() in msg.lower():
                return etype
    return "unknown"


def load_knowledge(exp_root: Path) -> list:
    kb = exp_root / KNOWLEDGE_FILE
    if not kb.exists():
        return []
    records = []
    with open(kb, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records


def save_record(exp_root: Path, record: dict):
    kb = exp_root / KNOWLEDGE_FILE
    exp_root.mkdir(parents=True, exist_ok=True)
    with open(kb, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_record(exp_root: Path, record_id: str, updates: dict) -> bool:
    records = load_knowledge(exp_root)
    found = False
    for rec in records:
        if rec.get("id") == record_id:
            rec.update(updates)
            found = True
            break
    if not found:
        return False
    kb = exp_root / KNOWLEDGE_FILE
    with open(kb, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


# ── record ──────────────────────────────────────────────
def cmd_record(args):
    exp_root = Path(args.exp_root).resolve()
    error_type = args.error_type or classify_error(args.error)
    rid = "err_" + uuid.uuid4().hex[:6]
    record = {
        "id": rid,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "round": args.round,
        "stage": args.stage,
        "factor": args.factor or None,
        "error_type": error_type,
        "error_msg": args.error,
        "root_cause": None,
        "fix": None,
        "fixed": False,
    }
    save_record(exp_root, record)
    print(f"📝 已记录错误: {rid}")
    print(f"   阶段: {STAGE_LABELS.get(args.stage, args.stage)}")
    print(f"   类型: {error_type}")
    print(f"   摘要: {args.error[:100]}")
    print(f"\n💡 定位原因后请标注:")
    print(f'   python collect_error.py annotate --exp-root "{exp_root}" --id {rid} \\')
    print(f'       --root-cause "<根本原因>" --fix "<修复方法>" --fixed')
    # 最后一行输出 ID，方便脚本用 grep/tail 解析
    print(f"\nERROR_ID={rid}")


# ── annotate ─────────────────────────────────────────────
def cmd_annotate(args):
    exp_root = Path(args.exp_root).resolve()
    updates = {}
    if args.root_cause: updates["root_cause"] = args.root_cause
    if args.fix:        updates["fix"] = args.fix
    if args.fixed:      updates["fixed"] = True
    if args.error_type: updates["error_type"] = args.error_type
    if not updates:
        print("⚠️  没有提供任何更新字段")
        sys.exit(1)
    if update_record(exp_root, args.id, updates):
        print(f"✅ 已更新记录 {args.id}: {list(updates.keys())}")
    else:
        print(f"❌ 未找到记录 {args.id}")
        print(f"   已有 ID: {[r['id'] for r in load_knowledge(exp_root)]}")
        sys.exit(1)


# ── query ────────────────────────────────────────────────
def cmd_query(args):
    exp_root = Path(args.exp_root).resolve()
    records = load_knowledge(exp_root)
    if not records:
        print("📭 错误知识库为空")
        return
    filtered = records
    if args.stage:
        filtered = [r for r in filtered if r.get("stage") == args.stage]
    if args.round is not None:
        filtered = [r for r in filtered if r.get("round", 0) < args.round]
    if args.unfixed_only:
        filtered = [r for r in filtered if not r.get("fixed")]
    if args.error_type:
        filtered = [r for r in filtered if r.get("error_type") == args.error_type]
    if not filtered:
        print("✅ 没有匹配的历史错误")
        return
    print(f"📚 {len(filtered)} 条相关历史错误:\n")
    for rec in filtered:
        flag = "✅ 已修复" if rec.get("fixed") else "⚠️  未修复"
        print(f"[{rec['id']}] Round {rec.get('round','?')} | "
              f"{rec.get('stage','')} | {rec.get('error_type','')} | {flag}")
        print(f"  因子: {rec.get('factor') or '(全局)'}")
        print(f"  错误: {rec.get('error_msg','')[:120]}")
        if rec.get("root_cause"): print(f"  原因: {rec['root_cause']}")
        if rec.get("fix"):        print(f"  修复: {rec['fix']}")
        print()


# ── list ─────────────────────────────────────────────────
def cmd_list(args):
    exp_root = Path(args.exp_root).resolve()
    records = load_knowledge(exp_root)
    if not records:
        print("📭 错误知识库为空")
        return
    if args.unfixed_only:
        records = [r for r in records if not r.get("fixed")]
        if not records:
            print("✅ 没有未修复错误")
            return
    print(f"{'ID':<12} {'轮':<4} {'阶段':<12} {'类型':<16} {'修复':<5} 摘要")
    print("-" * 82)
    for rec in records:
        fixed = "✅" if rec.get("fixed") else "❌"
        summary = rec.get("error_msg", "")[:35].replace("\n", " ")
        print(f"{rec.get('id',''):<12} {str(rec.get('round','?')):<4} "
              f"{rec.get('stage',''):<12} {rec.get('error_type',''):<16} "
              f"{fixed:<5} {summary}")
    total = len(records)
    fc = sum(1 for r in records if r.get("fixed"))
    print(f"\n共 {total} 条，{fc} 已修复，{total - fc} 未修复")


# ── summary ──────────────────────────────────────────────
def cmd_summary(args):
    """
    输出给 Agent 阅读的结构化历史经验摘要。
    借鉴 RD-Agent error_summary() 把历史错误注入提示词的思路：
    每轮开始前 Agent 读取此输出，主动在代码中避坑。
    """
    exp_root = Path(args.exp_root).resolve()
    records = load_knowledge(exp_root)
    cur = args.round or 0

    print("=" * 60)
    print(f"📚 历史错误知识库摘要（第 {cur} 轮开始前）")
    print("=" * 60)

    if not records:
        print("\n✅ 暂无历史错误记录，可放心开始新一轮。")
        print("=" * 60)
        return

    history = [r for r in records if r.get("round", 0) < cur] if cur > 0 else records
    unfixed = [r for r in history if not r.get("fixed")]
    fixed   = [r for r in history if r.get("fixed") and r.get("root_cause")]

    if unfixed:
        print(f"\n⚠️  【{len(unfixed)} 条未修复错误 — 本轮重点关注，避免重蹈覆辙】")
        for rec in unfixed:
            print(f"\n  [{rec['id']}] {STAGE_LABELS.get(rec.get('stage',''), rec.get('stage',''))}")
            print(f"  因子: {rec.get('factor') or '(全局)'}")
            print(f"  类型: {rec.get('error_type','unknown')}")
            print(f"  错误: {rec.get('error_msg','')[:120]}")
            if rec.get("root_cause"):
                print(f"  已知原因: {rec['root_cause']}")
            else:
                print(f"  ⚠️  根因未标注，请本轮确认后用 annotate 补充")
    else:
        print("\n✅ 没有遗留未修复错误")

    if fixed:
        print(f"\n💡 【{len(fixed)} 条已修复经验 — 写代码时对照避坑】")
        for rec in fixed[-8:]:
            print(f"\n  [{rec['id']}] {rec.get('stage','')} | {rec.get('error_type','')}")
            print(f"  错误: {rec.get('error_msg','')[:80]}")
            print(f"  ✅ 原因: {rec.get('root_cause','')}")
            print(f"  ✅ 修复: {rec.get('fix','')}")

    print("\n" + "=" * 60)
    print("📌 Agent 行动清单（编写代码前必读）:")
    print("  1. 对照未修复错误，检查本轮代码是否可能触发相同问题")
    print("  2. 对照已修复经验，主动在代码中加入防御性处理")
    print("  3. 本轮出现新错误后，立即用 record + annotate 命令记录")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="因子研发错误知识库")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record", help="记录错误（脚本失败时自动调用）")
    p.add_argument("--exp-root", required=True)
    p.add_argument("--round", type=int, default=0)
    p.add_argument("--stage", required=True, choices=list(STAGE_LABELS.keys()))
    p.add_argument("--factor", default=None)
    p.add_argument("--error", required=True)
    p.add_argument("--error-type", default=None)

    p = sub.add_parser("annotate", help="标注根因和修复（Agent 定位后调用）")
    p.add_argument("--exp-root", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--root-cause", default=None)
    p.add_argument("--fix", default=None)
    p.add_argument("--fixed", action="store_true")
    p.add_argument("--error-type", default=None)

    p = sub.add_parser("query", help="按条件查询历史错误")
    p.add_argument("--exp-root", required=True)
    p.add_argument("--round", type=int, default=None)
    p.add_argument("--stage", default=None, choices=list(STAGE_LABELS.keys()))
    p.add_argument("--error-type", default=None)
    p.add_argument("--unfixed-only", action="store_true")

    p = sub.add_parser("list", help="列出所有记录")
    p.add_argument("--exp-root", required=True)
    p.add_argument("--unfixed-only", action="store_true")

    p = sub.add_parser("summary", help="生成本轮开始前经验摘要（每轮必调用）")
    p.add_argument("--exp-root", required=True)
    p.add_argument("--round", type=int, default=0)

    args = parser.parse_args()
    {
        "record":   cmd_record,
        "annotate": cmd_annotate,
        "query":    cmd_query,
        "list":     cmd_list,
        "summary":  cmd_summary,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
