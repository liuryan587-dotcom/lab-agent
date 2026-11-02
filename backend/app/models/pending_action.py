from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PendingAction(Base):
    """Agent 发起、等待用户确认的写操作。

    为什么要有这张表：模型调用工具时不再直接写业务表，只留一条待确认记录。
    用户在前端点「确认」之后，才由服务端真正执行。
    这样即使模型被提示词注入说服，也拿不到直接改数据库的路径。

    状态机：0 待确认 → 1 已执行 / 2 已取消 / 3 已过期
    """

    __tablename__ = "pending_actions"
    __table_args__ = {"comment": "Agent 待确认的写操作"}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="发起人，只有本人能确认"
    )
    thread_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="所属会话。确认后要往这个会话里补一条「已提交」记录，模型下一轮才知道",
    )
    tool_name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="工具名，如 create_lab_reservation"
    )
    payload: Mapped[str] = mapped_column(
        Text, nullable=False, comment="工具参数的 JSON 原文，确认时重新校验"
    )
    status: Mapped[int] = mapped_column(
        Integer, default=0, comment="0待确认 1已执行 2已取消 3已过期"
    )
    expire_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="过期时间，过期后不能再确认"
    )
    executed_reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservations.id"), nullable=True, comment="执行成功后回填的预约 id"
    )


STATUS_PENDING = 0
STATUS_EXECUTED = 1
STATUS_CANCELLED = 2
STATUS_EXPIRED = 3
