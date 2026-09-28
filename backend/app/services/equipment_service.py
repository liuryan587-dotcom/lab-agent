from app.common.exceptions import BusinessException
from operator import or_
from app.models.equipment import Equipment
from app.schemas.equipment import (
    EquipmentCreateRequest,
    EquipmentResponse,
    EquipmentUpdateRequest,
)
from sqlalchemy.orm import Session
from app.utils.password import verify_password, hash_password
from app.common.response import PageResponse


def get_equipment_info(equipment: Equipment):
    return EquipmentResponse.model_validate(equipment)


def get_equipment_page_list(
    db: Session,
    page: int,
    page_size: int,
    keywords: str | None = None,
    lab_id: int | None = None,
):

    query = db.query(Equipment)
    if lab_id:
        query = query.filter(Equipment.lab_id == lab_id)
    if keywords:
        query = query.filter(Equipment.name.ilike(f"%{keywords}%"))
    total = query.count()
    items = (
        query.order_by(Equipment.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PageResponse(
        list=[EquipmentResponse.model_validate(item) for item in items], total=total
    )


def create_equipment(db: Session, data: EquipmentCreateRequest):
    """新增设备"""
    exist = db.query(Equipment).filter(Equipment.name == data.name).first()
    if exist:
        raise BusinessException(code=400, message="该设备已存在")
    equipment = Equipment(**data.model_dump())
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    res = EquipmentResponse.model_validate(equipment)
    res.lab_name = equipment.lab.name if equipment.lab else None
    return res


def update_equipment(db: Session, equipment_id: int, data: EquipmentUpdateRequest):
    """更新实验室"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(code=400, message="用户不存在")
    payload = data.model_dump(exclude_none=True)
    for field, value in payload.items():
        setattr(equipment, field, value)
    db.commit()
    db.refresh(equipment)
    return EquipmentResponse.model_validate(equipment)


def delete_equipment(db: Session, equipment_id: int):
    """删除实验室"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(code=400, message="该实验室不存在")
    db.delete(equipment)
    db.commit()
