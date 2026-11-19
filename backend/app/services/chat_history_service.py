"""会话历史：按 thread_id 保存完整的消息列表（含工具调用）。

为什么存 tool 消息：模型上一轮查到的结果如果丢了，下一轮问「那第二个呢」时
它只能重新查一遍。存下 ToolMessage 之后，同样的追问可以直接引用。
"""

import json
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy.orm import Session

from app.models.chat_message import ChatMessageRecord

# 每个 thread 最多回放多少条消息。长对话不能无限塞进上下文，
# 这里做最朴素的截断：保留最近 N 条。
MAX_HISTORY_MESSAGES = 40

# 时间敏感的工具：返回结果只在很短时间内有效。
# 会话恢复时如果把这些旧结果一起回放，模型会把几天前的日期、几天前的空位
# 当成「现在的事实」——它没有任何办法分辨这些 ToolMessage 是刚查的还是上周查的。
TIME_SENSITIVE_TOOLS = {"get_today", "find_lab_free_slots"}
TOOL_RESULT_TTL_MINUTES = 30


def _text(content) -> str:
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


def to_record(message: BaseMessage, thread_id: str, user_id: int):
    """LangChain 消息 → 表记录。SystemMessage 不落库（每轮重新拼）。"""
    if isinstance(message, HumanMessage):
        return ChatMessageRecord(
            thread_id=thread_id,
            user_id=user_id,
            role="user",
            content=_text(message.content),
        )
    if isinstance(message, AIMessage):
        payload = None
        if message.tool_calls:
            payload = json.dumps(
                [
                    {"name": c.get("name"), "args": c.get("args"), "id": c.get("id")}
                    for c in message.tool_calls
                ],
                ensure_ascii=False,
            )
        return ChatMessageRecord(
            thread_id=thread_id,
            user_id=user_id,
            role="assistant",
            content=_text(message.content),
            payload=payload,
        )
    if isinstance(message, ToolMessage):
        payload = json.dumps(
            {"tool_call_id": message.tool_call_id, "name": message.name},
            ensure_ascii=False,
        )
        return ChatMessageRecord(
            thread_id=thread_id,
            user_id=user_id,
            role="tool",
            content=_text(message.content),
            payload=payload,
        )
    return None


def to_langchain(record: ChatMessageRecord) -> BaseMessage | None:
    if record.role == "user":
        return HumanMessage(content=record.content)
    if record.role == "assistant":
        tool_calls = []
        if record.payload:
            try:
                tool_calls = json.loads(record.payload) or []
            except ValueError:
                tool_calls = []
        return AIMessage(content=record.content, tool_calls=tool_calls)
    if record.role == "tool":
        try:
            payload = json.loads(record.payload or "{}")
        except ValueError:
            payload = {}
        return ToolMessage(
            content=record.content,
            tool_call_id=payload.get("tool_call_id", ""),
            name=payload.get("name", ""),
        )
    return None


def append_messages(
    db: Session, thread_id: str, user_id: int, messages: list[BaseMessage]
) -> None:
    records = [to_record(message, thread_id, user_id) for message in messages]
    records = [record for record in records if record is not None]
    if not records:
        return
    db.add_all(records)
    db.commit()


def _payload_of(record: ChatMessageRecord) -> dict:
    try:
        return json.loads(record.payload or "{}") or {}
    except ValueError:
        return {}


def _stale_tool_turns(
    rows: list[ChatMessageRecord], now: datetime | None = None
) -> tuple[set[int], set[str]]:
    """找出已经过期的「时间敏感」工具结果。

    返回 (要丢弃的记录 id, 要丢弃的 tool_call_id)。

    为什么两个都要：ToolMessage 不能单独丢。它必须和那条带 tool_calls 的
    AIMessage 成对处理，否则 OpenAI 兼容接口会直接报
    "an assistant message with 'tool_calls' must be followed by tool messages"。
    """
    now = now or datetime.now()
    cutoff = now - timedelta(minutes=TOOL_RESULT_TTL_MINUTES)
    drop_ids: set[int] = set()
    stale_call_ids: set[str] = set()
    for row in rows:
        if row.role != "tool":
            continue
        payload = _payload_of(row)
        if payload.get("name") not in TIME_SENSITIVE_TOOLS:
            continue
        created = getattr(row, "create_time", None)
        # 没有时间戳的老数据一律当作过期：宁可重查一次，也别拿旧事实回答
        if created is None or created < cutoff:
            drop_ids.add(row.id)
            call_id = payload.get("tool_call_id") or ""
            if call_id:
                stale_call_ids.add(call_id)
    return drop_ids, stale_call_ids


def load_messages(db: Session, thread_id: str, user_id: int) -> list[BaseMessage]:
    rows = (
        db.query(ChatMessageRecord)
        .filter(
            ChatMessageRecord.thread_id == thread_id,
            ChatMessageRecord.user_id == user_id,  # 别人的会话读不到
        )
        .order_by(ChatMessageRecord.id.asc())
        .all()
    )
    if not rows:
        return []
    rows = rows[-MAX_HISTORY_MESSAGES:]

    drop_ids, stale_call_ids = _stale_tool_turns(rows)

    messages: list[BaseMessage] = []
    for row in rows:
        if row.id in drop_ids:
            continue
        message = to_langchain(row)
        if message is None:
            continue
        if isinstance(message, AIMessage) and message.tool_calls and stale_call_ids:
            remaining = [
                call
                for call in message.tool_calls
                if (call.get("id") or "") not in stale_call_ids
            ]
            if len(remaining) != len(message.tool_calls):
                if remaining or (row.content or "").strip():
                    message = AIMessage(content=row.content or "", tool_calls=remaining)
                else:
                    # 这条 assistant 只剩被丢弃的 tool_call，正文也是空的：整条丢掉
                    continue
        messages.append(message)
    return messages


def latest_thread_id(db: Session, user_id: int) -> str | None:
    """用户最近一次会话的 id。

    刷新页面时前端可能没有 thread_id（比如换浏览器、清过缓存、
    或者会话是在加这个功能之前开的），用它可以兜底恢复最近一次对话。
    """
    row = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.user_id == user_id)
        .order_by(ChatMessageRecord.id.desc())
        .first()
    )
    return row.thread_id if row else None


def list_display_messages(db: Session, thread_id: str, user_id: int) -> list[dict]:
    """给前端恢复界面用的简化消息。

    只返回 user / assistant 且有正文的：assistant 里那些带 tool_calls 的空消息
    是给模型看的，界面上不该出现空白气泡。
    """
    rows = (
        db.query(ChatMessageRecord)
        .filter(
            ChatMessageRecord.thread_id == thread_id,
            ChatMessageRecord.user_id == user_id,
        )
        .order_by(ChatMessageRecord.id.asc())
        .all()
    )
    messages = []
    for row in rows[-MAX_HISTORY_MESSAGES:]:
        if row.role not in ("user", "assistant"):
            continue
        if not (row.content or "").strip():
            continue
        messages.append({"role": row.role, "content": row.content})
    return messages
