from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.common.response import Response
from app.models.equipment import Equipment
from app.models.user import User
from app.dependencies.auth import get_current_admin, get_current_user
from app.schemas.equipment import (
    EquipmentCreateRequest,
    EquipmentUpdateRequest,
)
from app.services import equipment_service, reservation_service
from app.database import get_db

router = APIRouter(prefix="/equipment", tags=["实验室设备信息接口"])


@router.get("/{equipment_id}/starts")
def get_equipment_starts(
    equipment_id: int,
    day: date,
    duration: int = 60,
    step: int = 10,
    buffer: int = 10,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """某台设备某天还能开始预约的时刻。

    设备是独占资源（同一时段只能一个人用），并且默认留 10 分钟清理时间。
    """
    data = reservation_service.get_equipment_free_starts(
        db, equipment_id, day, duration=duration, step=step, buffer=buffer
    )
    return Response.success(data=data)


@router.get("/list")
def get_equipment_list(
    page: int = 1,
    page_size: int = 10,
    keywords: str | None = None,
    lab_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = equipment_service.get_equipment_page_list(
        db, page, page_size, keywords, lab_id
    )
    return Response.success(data=res)


@router.post("")
def create_equipment(
    data: EquipmentCreateRequest,
    current_user: Equipment = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = equipment_service.create_equipment(db, data)
    return Response.success(data=res)


@router.put("/{equipment_id}")
def update_equipment(
    equipment_id: int,
    data: EquipmentUpdateRequest,
    current_user: Equipment = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    res = equipment_service.update_equipment(db, equipment_id, data)
    return Response.success(data=res)


@router.delete("/{equipment_id}")
def delete_equipment(
    equipment_id: int,
    current_user: Equipment = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    equipment_service.delete_equipment(db, equipment_id)
    return Response.success()
