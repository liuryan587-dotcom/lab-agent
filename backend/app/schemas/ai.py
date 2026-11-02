from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    # 会话 id：前端第一次不传，后端生成并通过 SSE 的 thread 事件返回；
    # 之后每次带上它，服务端就能取出上一轮的完整消息（含工具调用结果）
    thread_id: str | None = None
