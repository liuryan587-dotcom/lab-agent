from app.common.exceptions import BusinessException
from operator import or_
from app.models.equipment import Equipment
from app.schemas.equipment import (
    EquipmentCreateRequest,
    EquipmentResponse,
    EquipmentUpdateRequest,
)
from sqlalchemy.orm import Session, joinedload
from app.utils.password import verify_password, hash_password
from app.common.response import PageResponse


def to_response(equipment: Equipment) -> EquipmentResponse:
    """统一出口：把「所属实验室」名称一并带上。

    lab_name 是 schema 里的可选字段，model_validate 不会自动填，
    之前只有 create_equipment 手工赋过值，导致列表和详情里这一列永远是 null，
    前端「所属实验室」列一直是空白。
    """
    res = EquipmentResponse.model_validate(equipment)
    res.lab_name = equipment.lab.name if equipment.lab else None
    return res


def get_equipment_info(equipment: Equipment):
    return to_response(equipment)


def get_equipment_page_list(
    db: Session,
    page: int,
    page_size: int,
    keywords: str | None = None,
    lab_id: int | None = None,
):

    # joinedload 预加载实验室，避免逐行懒加载造成 N+1
    query = db.query(Equipment).options(joinedload(Equipment.lab))
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
    return PageResponse(list=[to_response(item) for item in items], total=total)


def create_equipment(db: Session, data: EquipmentCreateRequest):
    """新增设备"""
    exist = db.query(Equipment).filter(Equipment.name == data.name).first()
    if exist:
        raise BusinessException(code=400, message="该设备已存在")
    equipment = Equipment(**data.model_dump())
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    return to_response(equipment)


def update_equipment(db: Session, equipment_id: int, data: EquipmentUpdateRequest):
    """更新设备"""
    equipment = (
        db.query(Equipment)
        .options(joinedload(Equipment.lab))
        .filter(Equipment.id == equipment_id)
        .first()
    )
    if not equipment:
        raise BusinessException(code=400, message="设备不存在")
    payload = data.model_dump(exclude_none=True)
    for field, value in payload.items():
        setattr(equipment, field, value)
    db.commit()
    db.refresh(equipment)
    return to_response(equipment)


def delete_equipment(db: Session, equipment_id: int):
    """删除设备"""
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise BusinessException(code=400, message="该设备不存在")
    db.delete(equipment)
    db.commit()
