from datetime import date as date_type
from datetime import time as time_type

from pydantic import BaseModel, ConfigDict, field_validator


class ReservationCreateRequest(BaseModel):
    lab_id: int
    equipment_id: int | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None


class ReservationResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None
    lab_id: int
    lab_name: str | None = None
    equipment_id: int | None = None
    equipment_name: str | None = None
    type: str | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)

    # date / start_time / end_time 在库里已经是 DATE / TIME 列，
    # 取出来是 datetime.date / datetime.time，这里统一转回字符串，
    # 保证给前端的 JSON 结构和以前完全一致（"2026-10-08" / "14:00"）
    @field_validator("date", mode="before")
    @classmethod
    def _format_date(cls, value):
        if isinstance(value, date_type):  # datetime 是 date 的子类，一并覆盖
            return value.strftime("%Y-%m-%d")
        return value

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def _format_time(cls, value):
        if isinstance(value, time_type):
            return value.strftime("%H:%M")
        return value


class ReservationStartsRequest(BaseModel):
    exsit: list[tuple[int, int]] = []
    open_start: int = 480
    open_end: int = 1260
    slot_duration: int = 60
    min_gap: int = 10
    buffer: int = 10


class AuditReservationRequest(BaseModel):
    status: int  #  1 | 2
