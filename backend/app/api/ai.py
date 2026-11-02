import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import (
    agent_service,
    chat_history_service,
    pending_action_service,
    trace_service,
)

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


# @router.post("/chat")
# def chat(
#     data: ChatRequest,
#     current_user: User = Depends(get_current_user),
# ):
#     content = agent_service.run_agent(current_user, data)
#     return Response.success(data=ChatMessage(role="assistant", content=content))


def _sse_line(payload: dict) -> str:
    """拼一条 SSE 帧：必须以data:开头，且以空行（\n\n）结束"""
    # ensure_ascii=Flase: 中文不要被转成 \uxxxx
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
):

    async def event_gen():
        # 内层异步生成器：取出业务事件，包装成 SSE 文本 再往外 yield
        # 必须 async：stream_agent 是 async generator，同步 for 会报
        # TypeError: 'async_generator' object is not iterable
        #
        # 注意这里不再传 db：每个工具自己开短生命周期 Session，
        # 请求级 Session 只服务于鉴权（get_current_user）
        async for event in agent_service.stream_agent(current_user, data):
            yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",  # 告诉浏览器这是SSE流
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 有 Nginx 时避免缓冲整段再吐
        },
    )


# ---------------------------------------------------------------- 待确认单
# Agent 调 create_lab_reservation 只会生成这里的记录，真正的落库发生在 confirm。
# 这样即使模型被提示词注入说服，也拿不到直接写 reservations 的路径。


@router.get("/pending-actions")
def list_pending_actions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Response.success(
        data=pending_action_service.list_pending(db, current_user.id)
    )


@router.post("/pending-actions/{action_id}/confirm")
def confirm_pending_action(
    action_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # confirm 内部会重新跑一遍预约的业务校验（TOCTOU）
    reservation = pending_action_service.confirm(db, current_user.id, action_id)
    return Response.success(
        data={
            "reservation_id": reservation.id,
            "status": reservation.status,
            "message": "预约已提交，请等待管理员审核",
        }
    )


@router.post("/pending-actions/{action_id}/cancel")
def cancel_pending_action(
    action_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pending_action_service.cancel(db, current_user.id, action_id)
    return Response.success(data={"cancelled": True})


@router.get("/history")
def get_history(
    thread_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """刷新页面后恢复对话：消息 + 还没确认的卡片。

    不传 thread_id 时退回到「当前用户最近一次会话」，
    这样即使前端丢了 id（清缓存、换设备、功能上线前的旧会话）也能恢复。
    """
    tid = thread_id or chat_history_service.latest_thread_id(db, current_user.id)
    if not tid:
        return Response.success(
            data={"thread_id": None, "messages": [], "pending_actions": []}
        )
    return Response.success(
        data={
            "thread_id": tid,
            "messages": chat_history_service.list_display_messages(
                db, tid, current_user.id
            ),
            "pending_actions": pending_action_service.list_by_thread(
                db, current_user.id, tid
            ),
        }
    )


@router.get("/traces")
def list_traces(
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Response.success(
        data=trace_service.list_recent(db, current_user.id, limit=min(limit, 100))
    )
