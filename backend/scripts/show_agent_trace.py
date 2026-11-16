"""打印一轮（或几轮）Agent 的执行链路，用来排查「模型/工具到底做了什么」。

数据来源全部是已有的落库记录，不重新跑模型：

1. agent_traces / agent_trace_steps —— 每轮概要 + 每次工具调用的入参、出参、耗时
2. pending_actions —— Agent 生成的待确认单（payload 原文 + 接口序列化后的样子）
3. chat_messages —— 该会话里保存的 user / assistant / tool 消息

用法（在 backend/ 目录下执行）：

    .venv\\Scripts\\python.exe scripts\\show_agent_trace.py
    .venv\\Scripts\\python.exe scripts\\show_agent_trace.py --thread t4a6ccb27aa24
    .venv\\Scripts\\python.exe scripts\\show_agent_trace.py --thread t4a6ccb27aa24 --limit 3
    .venv\\Scripts\\python.exe scripts\\show_agent_trace.py --json
    .venv\\Scripts\\python.exe scripts\\show_agent_trace.py --messages   # 连会话消息一起看

只想看接口的话，登录后也可以直接请求：
    GET /api/ai/traces?limit=20
    GET /api/ai/history?thread_id=xxx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models.agent_trace import AgentTrace, AgentTraceStep  # noqa: E402
from app.models.chat_message import ChatMessageRecord  # noqa: E402
from app.models.pending_action import PendingAction  # noqa: E402
from app.services import pending_action_service  # noqa: E402


def _pretty(raw: str | None) -> str:
    """工具入参/出参大多是 JSON，能格式化就格式化。"""
    if not raw:
        return "(empty)"
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return raw


def _latest_thread_id(db) -> str | None:
    row = db.query(AgentTrace).order_by(AgentTrace.id.desc()).first()
    return row.thread_id if row else None


def _load_traces(db, thread_id: str, limit: int) -> list[AgentTrace]:
    return (
        db.query(AgentTrace)
        .filter(AgentTrace.thread_id == thread_id)
        .order_by(AgentTrace.id.desc())
        .limit(limit)
        .all()
    )


def _as_dicts(db, traces: list[AgentTrace], messages: bool) -> list[dict]:
    steps = (
        db.query(AgentTraceStep)
        .filter(AgentTraceStep.trace_id.in_([t.id for t in traces]))
        .order_by(AgentTraceStep.trace_id.asc(), AgentTraceStep.step_index.asc())
        .all()
    )
    steps_by_trace: dict[int, list[dict]] = {}
    for step in steps:
        steps_by_trace.setdefault(step.trace_id, []).append(
            {
                "index": step.step_index,
                "name": step.name,
                "status": step.status,
                "latency_ms": step.latency_ms,
                "input": step.input,
                "output": step.output,
            }
        )

    result = []
    for trace in traces:
        item = {
            "trace_id": trace.id,
            "thread_id": trace.thread_id,
            "create_time": trace.create_time.isoformat(timespec="seconds"),
            "question": trace.question,
            "model": trace.model,
            "status": trace.status,
            "total_latency_ms": trace.total_latency_ms,
            "prompt_tokens": trace.prompt_tokens,
            "completion_tokens": trace.completion_tokens,
            "tool_call_count": trace.tool_call_count,
            "error_message": trace.error_message,
            "steps": steps_by_trace.get(trace.id, []),
        }
        if messages:
            item["messages"] = [
                {"role": m.role, "content": m.content, "payload": m.payload}
                for m in db.query(ChatMessageRecord)
                .filter(ChatMessageRecord.thread_id == trace.thread_id)
                .order_by(ChatMessageRecord.id.asc())
                .all()
            ]
        result.append(item)
    return result


def _pending_of(db, thread_id: str) -> list[dict]:
    """该会话下所有待确认单（不按状态过滤），并给出『接口会返回什么』。"""
    actions = (
        db.query(PendingAction)
        .filter(PendingAction.thread_id == thread_id)
        .order_by(PendingAction.id.asc())
        .all()
    )
    rows = []
    for action in actions:
        try:
            parsed = pending_action_service.serialize(db, action)
        except Exception as exc:  # noqa: BLE001
            parsed = {"serialize_error": str(exc)}
        rows.append(
            {
                "id": action.id,
                "status": action.status,
                "expire_at": action.expire_at.isoformat(timespec="seconds"),
                "payload_raw": action.payload,
                "serialized_for_card": parsed,
            }
        )
    return rows


def _card_line(serialized: dict) -> str:
    """模仿前端确认卡片的渲染，方便直接看出「卡片上会显示成什么」。"""
    lab = serialized.get("lab_name") or f"ID {serialized.get('lab_id')}"
    equipment = serialized.get("equipment_name")
    line = f"实验室：{lab}"
    if equipment:
        line += f" · 设备：{equipment}"
    line += (
        f"\n时间：{serialized.get('date')} "
        f"{serialized.get('start_time')}–{serialized.get('end_time')}"
    )
    return line


def main() -> int:
    parser = argparse.ArgumentParser(description="查看 Agent 执行链路")
    parser.add_argument("--thread", help="会话 id，省略时取最近一轮")
    parser.add_argument("--limit", type=int, default=1, help="打印最近几轮，默认 1")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    parser.add_argument("--messages", action="store_true", help="附带 chat_messages")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        thread_id = args.thread or _latest_thread_id(db)
        if not thread_id:
            print("数据库里还没有任何 Agent 轨迹（agent_traces 为空）")
            return 1
        traces = _load_traces(db, thread_id, max(1, args.limit))
        if not traces:
            print(f"thread={thread_id} 没有找到 agent_traces 记录")
            return 1

        data = {
            "thread_id": thread_id,
            "traces": _as_dicts(db, traces, args.messages),
            "pending_actions": _pending_of(db, thread_id),
        }

        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
            return 0

        print(f"会话 thread_id = {thread_id}")
        for trace in data["traces"]:
            print("\n" + "=" * 78)
            print(f"[trace {trace['trace_id']}] {trace['create_time']}  {trace['status']}")
            print(f"问题：{trace['question']}")
            print(
                f"模型：{trace['model']}  总耗时：{trace['total_latency_ms']}ms  "
                f"tokens：{trace['prompt_tokens']}+{trace['completion_tokens']}  "
                f"工具调用：{trace['tool_call_count']} 次"
            )
            if trace["error_message"]:
                print(f"错误：{trace['error_message']}")

            if not trace["steps"]:
                print("\n(本轮没有工具调用)")
            for step in trace["steps"]:
                print("\n" + "-" * 78)
                print(
                    f"step {step['index']}  {step['name']}  "
                    f"{step['latency_ms']}ms  status={step['status']}"
                )
                print("  入参：")
                for line in _pretty(step["input"]).splitlines():
                    print(f"    {line}")
                print("  出参：")
                for line in _pretty(step["output"]).splitlines():
                    print(f"    {line}")

            if args.messages:
                print("\n" + "-" * 78)
                print("会话消息（chat_messages）")
                for msg in trace["messages"]:
                    content = (msg["content"] or "").replace("\n", "\\n")
                    print(f"  [{msg['role']}] {content[:300]}")
                    if msg["payload"]:
                        print(f"      payload: {msg['payload']}")

        if data["pending_actions"]:
            print("\n" + "=" * 78)
            print("待确认单（pending_actions）")
            for action in data["pending_actions"]:
                print("\n" + "-" * 78)
                print(
                    f"action_id={action['id']}  status={action['status']}  "
                    f"expire_at={action['expire_at']}"
                )
                print("  DB payload：")
                for line in _pretty(action["payload_raw"]).splitlines():
                    print(f"    {line}")
                print("  接口 serialize 给卡片的数据：")
                for line in _pretty(
                    json.dumps(action["serialized_for_card"], ensure_ascii=False)
                ).splitlines():
                    print(f"    {line}")
                print("  卡片这一行应该显示成：")
                for line in _card_line(action["serialized_for_card"]).splitlines():
                    print(f"    {line}")

        print("\n提示：卡片显示「ID undefined / 时间 –」时，先看上面 pending 的 payload 是否为空；")
        print("      payload 正常但卡片为空，问题就在前端那次 GET /api/ai/pending-actions。")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
