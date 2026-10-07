import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.ai import ChatMessage, ChatRequest
from app.services import ai_service, agent_service

router = APIRouter(prefix="/ai", tags=["AI相关的API"])


@router.post("/chat")
def chat(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = agent_service.run_agent(db, current_user, data)
    return Response.success(data=ChatMessage(role="assistant", content=content))


def _sse_line(payload: dict) -> str:
    """拼一条 SSE 帧：必须以data:开头，且以空行（\n\n）结束"""
    # ensure_ascii=Flase: 中文不要被转成 \uxxxx
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    print("=== chat_stream 被调用了 ===")

    async def event_gen():
        # 内层异步生成器：取出业务事件，包装成 SSE 文本 再往外 yield
        # 必须 async：stream_agent 是 async generator，同步 for 会报
        # TypeError: 'async_generator' object is not iterable
        print("=== event_gen 开始迭代 ===")
        async for event in agent_service.stream_agent(db, current_user, data):
            yield _sse_line(event)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",  # 告诉浏览器这是SSE流
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 有 Nginx 时避免缓冲整段再吐
        },
    )
