from datetime import date, time

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Date, ForeignKey, String, Time
from app.models.lab import Lab
from app.database import Base
from app.models.user import User
from app.models.equipment import Equipment


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = {"comment": "预约信息"}

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), comment="预约人", nullable=False
    )
    lab_id: Mapped[int] = mapped_column(
        ForeignKey("labs.id"), comment="实验室", nullable=False
    )
    equipment_id: Mapped[int] = mapped_column(
        ForeignKey("equipments.id"), comment="设备，空表示只预约实验室", nullable=True
    )
    date: Mapped[date] = mapped_column(Date, comment="预约日期", nullable=False)
    start_time: Mapped[time] = mapped_column(Time, comment="开始时间", nullable=False)
    end_time: Mapped[time] = mapped_column(Time, comment="结束时间", nullable=False)
    remark: Mapped[str] = mapped_column(String(50), comment="备注", nullable=True)
    status: Mapped[int] = mapped_column(
        comment="预约状态：0待审核，1已通过，2已拒绝，3已取消", default=0
    )

    user: Mapped[User] = relationship()
    lab: Mapped[Lab] = relationship()
    equipment: Mapped[Equipment] = relationship()
