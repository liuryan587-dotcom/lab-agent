from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AgentTrace(Base):
    """一轮对话的概要。用来回答「线上 Agent 答错了怎么排查」。"""

    __tablename__ = "agent_traces"
    __table_args__ = {"comment": "Agent 每轮对话的轨迹"}

    thread_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="本轮用户输入（截断保存）"
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="success", comment="success / error"
    )
    total_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AgentTraceStep(Base):
    """一次工具调用。以后要做耗时瀑布图就从这张表出。"""

    __tablename__ = "agent_trace_steps"
    __table_args__ = {"comment": "Agent 轨迹里的单步（目前只有工具调用）"}

    trace_id: Mapped[int] = mapped_column(
        ForeignKey("agent_traces.id"), index=True, nullable=False
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tool", comment="tool / llm"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    input: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")
