#!/usr/bin/env python
"""lab-agent 评估集 runner。

在 backend 目录下执行：
    python tests/eval/runner.py                  # 跑全部 30 条
    python tests/eval/runner.py --only safety    # 只跑某一类
    python tests/eval/runner.py --only R01,T04   # 只跑指定 id
    python tests/eval/runner.py --limit 5        # 先试跑 5 条

产物：
    tests/eval/results/<时间戳>.json   每条样本的完整记录 + 指标
    控制台                              逐条结果 + markdown 指标表

依赖：
    - 本机 Ollama 在跑（rag 类样本会真的检索 Chroma）
    - .env 里的大模型配置可用
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = EVAL_DIR.parents[1]

# 让 `import app.*` 和 `import seed` 都能找到
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(EVAL_DIR))

CASE_TIMEOUT = 180


# --------------------------------------------------------------------- 工具函数
def parse_args(argv):
    parser = argparse.ArgumentParser(description="lab-agent 评估集 runner")
    parser.add_argument("--only", default="", help="按 id 或 category 过滤，逗号分隔")
    parser.add_argument(
        "--multi-turn",
        action="store_true",
        dest="multi_turn",
        help="跑多轮记忆评估集（真实两轮对话，走 thread_id）",
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    parser.add_argument(
        "--db", default=str(EVAL_DIR / ".cache" / "eval.db"), help="评估库路径"
    )
    parser.add_argument("--out", default="", help="结果 json 路径")
    parser.add_argument(
        "--chroma",
        default=str(EVAL_DIR / ".cache" / "chroma"),
        help="评估用的向量库目录（首次运行会从 data/chroma 复制一份）",
    )
    parser.add_argument("--recursion-limit", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=CASE_TIMEOUT, help="单条超时秒数")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="整轮重复次数。模型有随机性，看稳定性用（代价是成倍耗时）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="跳过解释器检查（明知道自己用的就是对的venv时）",
    )
    return parser.parse_args(argv)


def check_interpreter() -> bool:
    """确认跑的是 backend/.venv，而不是系统/conda 的 Python。

    用错解释器时，chromadb / langchain 会从别的 site-packages 导入，
    表现是版本冲突、导入卡死或者诡异报错，而且报错位置完全指不到真正原因。
    """
    venv = (BACKEND_ROOT / ".venv").resolve()
    current = Path(sys.prefix).resolve()
    if not venv.exists() or current == venv:
        return True

    print("=" * 68)
    print("Python 解释器不对，评估没有开始。")
    print("")
    print(f"  实际执行的文件：{sys.executable}")
    print(f"  它解析出的环境：{current}")
    print(f"  项目虚拟环境：{venv}")
    print("")
    print("项目的依赖（chromadb / langgraph / langchain-openai）只装在 .venv 里。")
    print("用别的解释器会从别的 site-packages 导入，表现为版本冲突或导入卡死。")
    print("")
    print("请改用项目虚拟环境的解释器：")
    print("  .\\.venv\\Scripts\\python.exe tests\\eval\\runner.py")
    print("")
    print("如果你确认用的就是上面这条命令、却仍然看到这个提示，")
    print("说明 .venv 本身有问题，先跑这条确认：")
    print("  .\\.venv\\Scripts\\python.exe -c \"import sys; print(sys.executable, sys.prefix)\"")
    print("")
    print("注意：暂时不要用 uv run / uv sync —— pyproject 里还没声明")
    print("langchain-openai 和 langgraph，uv 同步时可能把它们从 .venv 里删掉。")
    print("=" * 68)
    return False


def load_cases(multi_turn: bool = False):
    import yaml

    name = "dataset_multi_turn.yaml" if multi_turn else "dataset.yaml"
    path = EVAL_DIR / name
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def select_cases(cases, only, limit):
    if only:
        keys = {k.strip() for k in only.split(",") if k.strip()}
        cases = [
            c for c in cases if c.get("id") in keys or c.get("category") in keys
        ]
    if limit > 0:
        cases = cases[:limit]
    return cases


def check_ollama(timeout=3) -> bool:
    """rag 类样本要真的调 Ollama 做 embedding，先探一下活不活。"""
    import urllib.request

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def prepare_chroma(target, source):
    """把向量库复制一份给评估用。

    为什么要复制：Chroma 以读写方式打开 sqlite，和后端进程共用一个目录会抢锁，
    而且评估本身不该往业务向量库里写东西。复制一次之后复用，内容与线上一致。
    """
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        return target
    if not source.exists():
        print(f"警告：找不到向量库 {source}，rag 类样本会失败")
        return source
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(source, target, dirs_exist_ok=True)
        print(f"向量库已复制到：{target}")
        return target
    except Exception as exc:
        print(f"警告：复制向量库失败（{exc}），改用原目录；请先停掉后端再跑")
        return source


def text_of(content) -> str:
    """AIMessage/ToolMessage 的 content 可能是 str，也可能是块列表。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content)


def extract_result(result) -> dict:
    """从 ainvoke 返回的 state 里抠出工具调用、工具输出、最终回答和 token。"""
    from langchain_core.messages import AIMessage, ToolMessage

    tool_calls = []
    tool_outputs = {}
    answer = ""
    prompt_tokens = 0
    completion_tokens = 0

    for message in result.get("messages", []):
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                tool_calls.append({"name": call.get("name"), "args": call.get("args")})
            text = text_of(message.content)
            if text.strip():
                answer = text
            usage = getattr(message, "usage_metadata", None) or {}
            prompt_tokens += usage.get("input_tokens") or 0
            completion_tokens += usage.get("output_tokens") or 0
        elif isinstance(message, ToolMessage):
            tool_outputs[message.tool_call_id] = text_of(message.content)

    return {
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "answer": answer,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
    }


# --------------------------------------------------------------------- 断言
def resolve_expected(value):
    """把数据集里的 $today / $tomorrow 换成真实日期字符串。"""
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    today = date.today()
    offsets = {
        "$today": today,
        "$tomorrow": today + timedelta(days=1),
        "$yesterday": today - timedelta(days=1),
    }
    target = offsets.get(value)
    return target.isoformat() if target else value


_CN_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_SLASH_DATE = re.compile(r"(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})")


def normalize_answer(text: str) -> str:
    """把「2026年11月19日」「2026/11/19」统一成「2026-11-19」。

    模型回答日期时习惯用中文写法，而 $today 断言比的是 ISO 串。
    不归一化的话，样本会因为「写法不同」而红，看起来像模型答错了。
    """

    def _to_iso(m):
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    return _SLASH_DATE.sub(_to_iso, _CN_DATE.sub(_to_iso, text))


def norm_arg(key, value):
    """统一参数形态再比较：id 一律按字符串、时间去掉秒。"""
    text = "" if value is None else str(value).strip()
    if key.endswith("_time") and len(text) == 8 and text.count(":") == 2:
        return text[:5]  # 14:00:00 -> 14:00
    return text


def check_tool_args(exp, run, fails) -> bool:
    """逐个校验工具调用的参数。

    只查「调了哪个工具」是不够的：模型完全可能调对工具、却把实验室或时段传错，
    用户拿到的是错误预约。这一层断言就是堵这个口子。
    """
    ok = True
    for tool_name, expected_args in exp["tool_args"].items():
        calls = [c for c in run["tool_calls"] if c["name"] == tool_name]
        if not calls:
            ok = False
            fails.append(f"没有调用 {tool_name}，无法校验参数")
            continue
        actual = calls[-1].get("args") or {}
        for key, expected in expected_args.items():
            want = resolve_expected(expected)
            got = actual.get(key)
            if norm_arg(key, got) != norm_arg(key, want):
                ok = False
                fails.append(f"{tool_name}.{key} = {got!r}, 期望 {want!r}")
    return ok


def evaluate(case, run, delta) -> tuple[dict, list]:
    """返回 (各维度的通过标记, 失败原因列表)。"""
    exp = case.get("expect") or {}
    names = [call["name"] for call in run["tool_calls"]]
    checks = {
        "tools": None,
        "order": None,
        "doc": None,
        "answer": None,
        "db": None,
        "write_blocked": None,
        "args": None,
    }
    fails = []

    if "tools" in exp:
        ok = sorted(set(names)) == sorted(set(exp["tools"]))
        checks["tools"] = ok
        if not ok:
            fails.append(f"工具集合不符: 期望 {exp['tools']}, 实际 {names}")

    if "tools_include" in exp:
        missing = [name for name in exp["tools_include"] if name not in names]
        if missing:
            fails.append(f"缺少必需工具: {missing}")

    if "tools_any" in exp:
        # 同一个问题往往有多条合法路径，这里只要求「命中其中之一」
        if not any(name in names for name in exp["tools_any"]):
            fails.append(f"没有调用以下任一工具: {exp['tools_any']}, 实际 {names}")

    if "tool_args" in exp:
        checks["args"] = check_tool_args(exp, run, fails)

    if "must_not_tools" in exp:
        banned = [name for name in exp["must_not_tools"] if name in names]
        # 模型有没有被说服，看这一项——它衡量的是「模型合规」，不是「系统安全」
        checks["write_blocked"] = not banned
        if banned:
            fails.append(f"调用了禁止的工具: {banned}")

    if "tool_order" in exp:
        ok = names == exp["tool_order"]
        checks["order"] = ok
        if not ok:
            fails.append(f"工具顺序不符: 期望 {exp['tool_order']}, 实际 {names}")

    if "doc" in exp:
        needle = f"[{exp['doc']}.md]"
        ok = any(needle in text for text in run["tool_outputs"].values())
        checks["doc"] = ok
        if not ok:
            fails.append(f"检索未命中文档 {needle}")

    if "answer_contains" in exp or "answer_not_contains" in exp:
        # 和 tool_args 保持一致：$today / $tomorrow 要换成真实日期再比，
        # 否则样本只能写死某一天，第二天必然失效。
        # 回答先归一化：中文日期写法不该导致样本误红。
        answer = normalize_answer(run["answer"])
        missing = [
            k
            for k in exp.get("answer_contains", [])
            if resolve_expected(k) not in answer
        ]
        banned = [
            k
            for k in exp.get("answer_not_contains", [])
            if resolve_expected(k) in answer
        ]
        checks["answer"] = not missing and not banned
        if missing:
            fails.append(f"回答缺少关键词: {missing}")
        if banned:
            fails.append(f"回答包含禁止词: {banned}")

    if "db_delta" in exp:
        # delta 是 {"reservations": n, "pending_actions": m}
        ok = True
        for table, want in exp["db_delta"].items():
            got = delta.get(table, 0)
            if got != int(want):
                ok = False
                fails.append(f"{table} 增量 {got}, 期望 {want}")
        checks["db"] = ok

    return checks, fails


# --------------------------------------------------------------------- 执行
async def run_case(case, args, student_username):
    from app.database import SessionLocal
    from app.models.pending_action import PendingAction
    from app.models.reservation import Reservation
    from app.models.user import User
    from app.schemas.ai import ChatMessage, ChatRequest
    from app.services import agent_service

    import seed

    # 每条样本都从干净的库开始，样本之间不会互相污染
    seed.reset()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == student_username).one()
        before = {
            "reservations": db.query(Reservation).count(),
            "pending_actions": db.query(PendingAction).count(),
        }
    finally:
        db.close()

    history = case.get("messages") or [
        {"role": "user", "content": case.get("question", "")}
    ]
    request = ChatRequest(messages=[ChatMessage(**item) for item in history])
    # 复用生产代码的输入构造（内含「当前时间」注入），保证评估和线上行为一致。
    # 以前这里自己拼 SystemMessage，绕过了注入，测出来的行为和线上不一样。
    inputs = agent_service.build_initial_messages(agent_service._build_history(request))

    agent = agent_service.build_agent(user)

    started = time.perf_counter()
    error = ""
    result = None
    try:
        result = await asyncio.wait_for(
            agent.ainvoke(
                inputs, config={"recursion_limit": args.recursion_limit}
            ),
            timeout=args.timeout,
        )
    except Exception as exc:  # 单条失败不能中断整轮评估
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - started) * 1000)

    db = SessionLocal()
    try:
        after = {
            "reservations": db.query(Reservation).count(),
            "pending_actions": db.query(PendingAction).count(),
        }
    finally:
        db.close()
    delta = {key: after[key] - before[key] for key in after}

    run = extract_result(result) if result else {
        "tool_calls": [],
        "tool_outputs": {},
        "answer": "",
        "tokens": {"prompt": 0, "completion": 0},
    }

    checks, fails = evaluate(case, run, delta)
    if error:
        fails.append(f"执行异常: {error}")

    return {
        "id": case["id"],
        "category": case["category"],
        "question": case.get("question") or "\n".join(
            item.get("content", "") for item in history if item.get("role") == "user"
        ),
        "expect": case.get("expect") or {},
        "passed": not fails,
        "fails": fails,
        "checks": checks,
        "latency_ms": latency_ms,
        "tokens": run["tokens"],
        "tools": [call["name"] for call in run["tool_calls"]],
        "tool_calls": run["tool_calls"],
        "tool_outputs": run["tool_outputs"],
        "answer": run["answer"][:500],
        "error": error,
    }


async def run_multi_turn_case(case, args, student_username):
    """跑一段真实的多轮对话（服务端 thread_id + 完整消息历史）。

    和 run_case 的区别：这里每一轮都是一次真实的 stream_agent 调用，
    中间不 reset 数据库，所以第二轮能看到第一轮存在 chat_messages 里的
    tool 结果。断言的核心是「第 N 轮用了几个工具」。
    """
    from app.database import SessionLocal
    from app.models.user import User
    from app.schemas.ai import ChatMessage, ChatRequest
    from app.services import agent_service

    import seed

    seed.reset()

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == student_username).one()
    finally:
        db.close()

    turns = case.get("turns") or []
    exp = case.get("expect") or {}
    caps = exp.get("tools_per_turn_max") or []

    thread_id = None
    turn_records = []
    final_answer = ""
    error = ""
    prompt_tokens = completion_tokens = 0

    started = time.perf_counter()
    try:
        for text in turns:
            request = ChatRequest(
                messages=[ChatMessage(role="user", content=text)],
                thread_id=thread_id,
            )
            used = []
            answer = ""
            async for event in agent_service.stream_agent(user, request):
                kind = event.get("type")
                if kind == "thread":
                    thread_id = event["thread_id"]
                elif kind == "tool_start":
                    used.append(event.get("name"))
                elif kind == "token":
                    answer += event.get("content") or ""
                elif kind == "error":
                    raise RuntimeError(event.get("message"))
            turn_records.append({"text": text, "tools": used, "answer": answer})
            final_answer = answer
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - started) * 1000)

    fails = []
    for index, cap in enumerate(caps):
        if index >= len(turn_records):
            break
        got = len(turn_records[index]["tools"])
        if got > cap:
            names = ",".join(turn_records[index]["tools"]) or "-"
            fails.append(f"第 {index + 1} 轮工具调用 {got} 次（{names}），上限 {cap}")

    missing = [k for k in exp.get("answer_contains", []) if k not in final_answer]
    if missing:
        fails.append(f"回答缺少关键词: {missing}")
    if error:
        fails.append(f"执行异常: {error}")

    # token 用量从 stream_agent 落下的 trace 里取
    from app.models.agent_trace import AgentTrace

    db = SessionLocal()
    try:
        traces = (
            db.query(AgentTrace).filter(AgentTrace.thread_id == thread_id).all()
            if thread_id
            else []
        )
        prompt_tokens = sum(t.prompt_tokens for t in traces)
        completion_tokens = sum(t.completion_tokens for t in traces)
    finally:
        db.close()

    checks = {
        "tools": None,
        "order": None,
        "doc": None,
        "answer": not missing,
        "db": None,
        "write_blocked": None,
        "args": None,
        "turns": not fails,
    }

    return {
        "id": case["id"],
        "category": case["category"],
        "question": "\n".join(case.get("turns", [])),
        "expect": exp,
        "passed": not fails,
        "fails": fails,
        "checks": checks,
        "latency_ms": latency_ms,
        "tokens": {"prompt": prompt_tokens, "completion": completion_tokens},
        "tools": [name for turn in turn_records for name in turn["tools"]],
        "turn_tools": [turn["tools"] for turn in turn_records],
        "turn_answers": [turn["answer"][:200] for turn in turn_records],
        "turns": turn_records,
        "thread_id": thread_id,
        "answer": final_answer[:500],
        "error": error,
    }


# --------------------------------------------------------------------- 指标与报告
def ratio(values):
    values = [v for v in values if v is not None]
    if not values:
        return None, 0
    return sum(1 for v in values if v), len(values)


def percentile(values, pct):
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def summarize(records):
    active = [r for r in records if not r.get("skipped")]
    total = len(active)
    passed = sum(1 for r in active if r["passed"])

    metrics = {}
    metrics["端到端完成率"] = ratio([r["passed"] for r in active])
    metrics["工具选择准确率"] = ratio(
        [r["checks"]["tools"] for r in active if r["checks"]["tools"] is not None]
    )
    metrics["工具参数正确率"] = ratio(
        [r["checks"].get("args") for r in active if r["checks"].get("args") is not None]
    )
    metrics["工具顺序正确率"] = ratio(
        [r["checks"]["order"] for r in active if r["checks"]["order"] is not None]
    )
    metrics["检索命中率"] = ratio(
        [r["checks"]["doc"] for r in active if r["checks"]["doc"] is not None]
    )
    # 安全只保留一个硬指标：业务表有没有被写进去。
    # 模型是否被说服（write_blocked）已经不重要了——写库路径在代码层被拿走了，
    # 所以不再作为指标输出，避免和「系统安全」混为一谈。
    metrics["系统写安全率"] = ratio(
        [r["checks"]["db"] for r in active if r["category"] == "safety"]
    )
    metrics["多轮记忆命中率"] = ratio(
        [r["passed"] for r in active if r["category"] == "multi_turn_memory"]
    )

    latencies = [r["latency_ms"] for r in active]
    tokens = [r["tokens"]["prompt"] + r["tokens"]["completion"] for r in active]

    # 多轮模式的核心数字：第二轮还用了几次工具
    second_turn = [
        len(r["turn_tools"][1])
        for r in active
        if r.get("turn_tools") and len(r["turn_tools"]) > 1
    ]

    return {
        "total": total,
        "passed": passed,
        "skipped": len(records) - total,
        "metrics": metrics,
        "latency_avg_ms": int(sum(latencies) / total) if total else 0,
        "latency_p95_ms": percentile(latencies, 95),
        "tokens_avg": int(sum(tokens) / total) if total else 0,
        "second_turn": {
            "count": len(second_turn),
            "total_tools": sum(second_turn),
            "avg": round(sum(second_turn) / len(second_turn), 2) if second_turn else None,
        },
    }


def compute_stability(records):
    """按样本统计重复多轮时的通过次数，用来区分「真失败」和「抖动」。"""
    stats = {}
    for record in records:
        if record.get("skipped"):
            continue
        bucket = stats.setdefault(record["id"], [0, 0])
        bucket[1] += 1
        bucket[0] += 1 if record["passed"] else 0
    return stats


def render_report(records, summary, meta, stability=None):
    lines = []
    lines.append("")
    lines.append(f"模型：{meta['model']}    递归上限：{meta['recursion_limit']}")
    lines.append("=" * 68)

    for record in records:
        if record.get("skipped"):
            lines.append(f"[SKIP] {record['id']:<4} {record['category']:<11}      -  -")
            continue
        flag = "PASS" if record["passed"] else "FAIL"
        if record.get("turn_tools") is not None:
            tools = "turns=" + str([len(t) for t in record["turn_tools"]])
        else:
            tools = ",".join(record["tools"]) or "-"
        lines.append(
            f"[{flag}] {record['id']:<4} {record['category']:<11} "
            f"{record['latency_ms']:>6}ms  {tools}"
        )
        for fail in record["fails"]:
            lines.append(f"        └─ {fail}")

    lines.append("=" * 68)
    lines.append("")
    lines.append("## 指标")
    lines.append("")
    lines.append("| 指标 | 结果 | 样本数 |")
    lines.append("|---|---|---|")

    for name, (ok, count) in summary["metrics"].items():
        if ok is None:
            lines.append(f"| {name} | — | 0 |")
        else:
            lines.append(f"| {name} | {ok}/{count} = {ok / count:.1%} | {count} |")

    lines.append(
        f"| 平均延迟 | {summary['latency_avg_ms']} ms | {summary['total']} |"
    )
    lines.append(f"| P95 延迟 | {summary['latency_p95_ms']} ms | {summary['total']} |")
    lines.append(f"| 平均 token | {summary['tokens_avg']} | {summary['total']} |")

    second = summary.get("second_turn") or {}
    if second.get("avg") is not None:
        lines.append(
            f"| 第二轮平均工具调用 | {second['avg']} 次 "
            f"（合计 {second['total_tools']} 次） | {second['count']} |"
        )

    if summary.get("skipped"):
        lines.append("")
        lines.append(f"跳过 {summary['skipped']} 条（Ollama 不可用，rag 类未计入统计）")

    lines.append("")
    lines.append("## 分类通过率")
    lines.append("")
    lines.append("| 类别 | 通过 | 合计 |")
    lines.append("|---|---|---|")
    categories = {}
    for record in records:
        if record.get("skipped"):
            continue
        bucket = categories.setdefault(record["category"], [0, 0])
        bucket[1] += 1
        bucket[0] += 1 if record["passed"] else 0
    for category, (ok, count) in categories.items():
        lines.append(f"| {category} | {ok} | {count} |")

    if stability and meta.get("repeat", 1) > 1:
        unstable = {
            cid: (ok, total) for cid, (ok, total) in stability.items() if ok < total
        }
        lines.append("")
        lines.append(f"## 稳定性（共 {meta['repeat']} 轮）")
        lines.append("")
        if not unstable:
            lines.append("全部样本每轮都通过。")
        else:
            lines.append("| 样本 | 通过轮数 | 说明 |")
            lines.append("|---|---|---|")
            for cid, (ok, total) in unstable.items():
                kind = "稳定失败" if ok == 0 else "抖动"
                lines.append(f"| {cid} | {ok}/{total} | {kind} |")

    return "\n".join(lines)


# --------------------------------------------------------------------- 入口
def main(argv=None):
    args = parse_args(argv or sys.argv[1:])

    if not args.force and not check_interpreter():
        return 1

    db_path = Path(args.db).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    # 必须在导入 app.* 之前设置：pydantic-settings 的环境变量优先级高于 .env
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path.as_posix()

    from app.config import settings

    cases = select_cases(load_cases(args.multi_turn), args.only, args.limit)
    if not cases:
        print("没有匹配的样本，检查 --only 参数")
        return 1

    print(f"评估库：{db_path}")
    print(f"样本数：{len(cases)}")

    # 向量库隔离：必须在第一次检索之前把 kb_service 的目录指过去
    chroma_dir = prepare_chroma(args.chroma, BACKEND_ROOT / "data" / "chroma")
    from app.services import kb_service

    kb_service.CHROMA_DIR = chroma_dir
    kb_service._collection = None

    import seed

    ollama_ok = check_ollama()
    if not ollama_ok and any(c["category"] == "rag" for c in cases):
        print("")
        print("!" * 68)
        print("警告：连不上 Ollama（http://localhost:11434），rag 类样本将被跳过。")
        print("     先启动 Ollama 再跑，才能得到完整的检索指标。")
        print("!" * 68)

    records = []
    started = time.perf_counter()
    for run_index in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n--- 第 {run_index}/{args.repeat} 轮 ---")
        for index, case in enumerate(cases, start=1):
            print(f"  [{index}/{len(cases)}] {case['id']} ...", end="", flush=True)
            if case["category"] == "rag" and not ollama_ok:
                records.append(
                    {
                        "id": case["id"],
                        "category": case["category"],
                        "expect": case.get("expect") or {},
                        "passed": False,
                        "skipped": True,
                        "fails": ["跳过：Ollama 不可用"],
                        "checks": {
                            "tools": None,
                            "order": None,
                            "doc": None,
                            "answer": None,
                            "db": None,
                            "write_blocked": None,
                            "args": None,
                        },
                        "latency_ms": 0,
                        "tokens": {"prompt": 0, "completion": 0},
                        "tools": [],
                        "answer": "",
                        "error": "",
                    }
                )
                print(" SKIP")
                continue

            record = asyncio.run(
                (
                    run_multi_turn_case(case, args, seed.STUDENT_USERNAME)
                    if "turns" in case
                    else run_case(case, args, seed.STUDENT_USERNAME)
                )
            )
            records.append(record)
            if record.get("turn_tools") is not None:
                print(
                    " PASS" if record["passed"] else " FAIL",
                    "turns=" + str([len(t) for t in record["turn_tools"]]),
                )
            else:
                print(" PASS" if record["passed"] else " FAIL")

    elapsed = time.perf_counter() - started

    summary = summarize(records)
    stability = compute_stability(records)
    meta = {
        "model": settings.LLM_MODEL,
        "base_url": settings.LLM_BASE_URL,
        "ollama_available": ollama_ok,
        "recursion_limit": args.recursion_limit,
        "repeat": args.repeat,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(elapsed, 1),
        "dataset": "tests/eval/dataset_multi_turn.yaml" if args.multi_turn else "tests/eval/dataset.yaml",
        "dataset_sha256": hashlib.sha256(
            (EVAL_DIR / ("dataset_multi_turn.yaml" if args.multi_turn else "dataset.yaml"))
            .read_bytes()
        ).hexdigest(),
    }

    print(render_report(records, summary, meta, stability))

    out_path = (
        Path(args.out)
        if args.out
        else EVAL_DIR / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": meta,
        "summary": {
            **summary,
            "metrics": {
                name: {"ok": ok, "count": count}
                for name, (ok, count) in summary["metrics"].items()
            },
        },
        "records": records,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n结果已写入：{out_path}")
    return 0 if summary["passed"] == summary["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
