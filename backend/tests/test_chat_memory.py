"""会话记忆：过期工具结果的过滤规则。

背景：会话恢复时会把历史消息（含 ToolMessage）原样回放给模型。
时间敏感的旧结果如果一起回放，模型会把几天前的日期、几天前的空位当成现在的事实。
这里锁定"哪些该丢、哪些该留"。
"""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from app.services.chat_history_service import _stale_tool_turns


def row(idx, role, name=None, call_id=None, at=None):
    payload = (
        json.dumps({"tool_call_id": call_id, "name": name}, ensure_ascii=False)
        if role == "tool"
        else "[]"
    )
    return NS(id=idx, role=role, payload=payload, create_time=at, content="")


def test_old_time_sensitive_result_is_dropped():
    old = datetime.now() - timedelta(hours=48)
    drop, calls = _stale_tool_turns(
        [
            row(1, "assistant"),
            row(2, "tool", "find_lab_free_slots", "c1", old),
        ]
    )
    assert drop == {2}
    # 成对丢弃：tool_call_id 必须一起报出去，否则外面摘不掉 AIMessage.tool_calls
    assert calls == {"c1"}


def test_fresh_result_is_kept():
    drop, calls = _stale_tool_turns(
        [
            row(1, "assistant"),
            row(2, "tool", "get_today", "c1", datetime.now()),
        ]
    )
    assert drop == set()
    assert calls == set()


def test_old_but_not_time_sensitive_is_kept():
    old = datetime.now() - timedelta(days=7)
    drop, _ = _stale_tool_turns(
        [
            row(2, "tool", "list_open_labs", "c1", old),
        ]
    )
    assert drop == set()


def test_missing_create_time_counts_as_stale():
    # 没有时间戳的老数据一律当作过期：宁可重查一次，也别拿旧事实回答
    drop, _ = _stale_tool_turns(
        [
            row(2, "tool", "get_today", "c1", None),
        ]
    )
    assert drop == {2}


def test_system_prompt_contains_today():
    from app.services.agent_service import _system_prompt

    prompt = _system_prompt()
    assert datetime.now().strftime("%Y-%m-%d") in prompt
