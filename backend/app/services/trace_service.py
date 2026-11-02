"""把每轮对话的轨迹落库。

目的不是做监控大盘，是让「线上这轮为什么答错了」能查：哪一步、调了什么工具、
传了什么参、花了多久、哪一步失败。
"""

import json

from sqlalchemy.orm import Session

from app.models.agent_trace import AgentTrace, AgentTraceStep

MAX_QUESTION = 500
MAX_STEP_IO = 1000


def _clip(text, limit: int) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def list_recent(db: Session, user_id: int, limit: int = 20) -> list[dict]:
    """最近几轮对话的轨迹，按时间倒序。前端可以拿它做排查面板。"""
    traces = (
        db.query(AgentTrace)
        .filter(AgentTrace.user_id == user_id)
        .order_by(AgentTrace.id.desc())
        .limit(limit)
        .all()
    )
    if not traces:
        return []

    trace_ids = [trace.id for trace in traces]
    steps = (
        db.query(AgentTraceStep)
        .filter(AgentTraceStep.trace_id.in_(trace_ids))
        .order_by(AgentTraceStep.step_index.asc())
        .all()
    )
    steps_by_trace: dict[int, list[dict]] = {}
    for step in steps:
        steps_by_trace.setdefault(step.trace_id, []).append(
            {
                "index": step.step_index,
                "name": step.name,
                "latency_ms": step.latency_ms,
                "status": step.status,
                "input": step.input,
                "output": step.output,
            }
        )

    return [
        {
            "id": trace.id,
            "thread_id": trace.thread_id,
            "question": trace.question,
            "model": trace.model,
            "status": trace.status,
            "total_latency_ms": trace.total_latency_ms,
            "prompt_tokens": trace.prompt_tokens,
            "completion_tokens": trace.completion_tokens,
            "tool_call_count": trace.tool_call_count,
            "error_message": trace.error_message,
            "create_time": trace.create_time.isoformat(timespec="seconds"),
            "steps": steps_by_trace.get(trace.id, []),
        }
        for trace in traces
    ]


def record(
    db: Session,
    *,
    thread_id: str,
    user_id: int,
    question: str,
    model: str,
    status: str,
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    tool_steps: list[dict] | None = None,
    error_message: str = "",
) -> AgentTrace:
    tool_steps = tool_steps or []

    trace = AgentTrace(
        thread_id=thread_id,
        user_id=user_id,
        question=_clip(question, MAX_QUESTION),
        model=model,
        status=status,
        total_latency_ms=latency_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_call_count=len(tool_steps),
        error_message=_clip(error_message, MAX_STEP_IO),
    )
    db.add(trace)
    db.flush()  # 拿到 trace.id

    for index, step in enumerate(tool_steps):
        db.add(
            AgentTraceStep(
                trace_id=trace.id,
                step_index=index,
                step_type="tool",
                name=step.get("name", ""),
                input=_clip(step.get("input"), MAX_STEP_IO),
                output=_clip(step.get("output"), MAX_STEP_IO),
                latency_ms=int(step.get("latency_ms") or 0),
                status=step.get("status", "ok"),
            )
        )

    db.commit()
    return trace
