from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ChatMessageRecord(Base):
    """按 thread 持久化的对话消息。

    为什么不用 LangGraph 的 checkpointer：这个项目需要的是「跨请求记得上一轮
    查到了什么」，而不是「图执行到一半能续跑」。存完整消息列表已经够用，
    也不引入新的依赖。

    关键点：**tool 消息也要存**。之前前端只回传 user/assistant 的纯文本，
    模型看不到上一轮工具查回来的结果，只能重新查一遍。
    """

    __tablename__ = "chat_messages"
    __table_args__ = {"comment": "按会话保存的对话消息（含工具调用）"}

    thread_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="会话 id"
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="归属用户"
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="user / assistant / tool"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="消息正文"
    )
    payload: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="JSON：assistant 存 tool_calls，tool 存 tool_call_id/name",
    )
