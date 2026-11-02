from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy import create_engine, DateTime
from app.config import settings
from datetime import datetime

# 评估集跑在 SQLite 上，而 Agent 的工具是在线程池里执行的。
# SQLite 默认禁止连接跨线程复用，这里对 SQLite 放开；MySQL 不受影响。
_connect_args: dict = {}
if settings.DATABASE_URL.startswith("sqlite"):
    _connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)

# 数据库session会话的连接工厂
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Base(DeclarativeBase):
    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="主键ID", sort_order=-1
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, comment="创建时间", sort_order=1
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        comment="更新时间",
        sort_order=2,
    )
