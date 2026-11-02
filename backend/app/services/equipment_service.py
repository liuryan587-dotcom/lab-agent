import json
from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.common.exceptions import BusinessException
from app.common.response import PageResponse
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.schemas.equipment import (
    EquipmentCreateRequest,
    EquipmentResponse,
    EquipmentUpdateRequest,
)


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
    # 必须用 is not None：lab_id=0 是「查 lab_id 为 0 的设备」，不是「不筛选」
    if lab_id is not None:
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


# 同义词组：查询命中组内任意一个词，就用整组去匹配 name / spec / description。
# 为什么不用「单向映射」：设备可能叫「显卡」，也可能叫「GPU计算节点」或「A100」，
# 单向映射会出现「搜 gpu 有 3 条、搜显卡只有 2 条」这种不一致。
SYNONYM_GROUPS = [
    # 算力设备：这三台是同一类，用户说哪个词都该搜到同一批
    ["显卡", "gpu", "a100", "算力"],
    # 服务器 / 存储
    ["服务器", "工作站", "存储"],
    # 网络设备
    ["网络", "交换机", "路由器", "防火墙"],
    # 视觉采集
    ["相机", "摄像头", "视觉"],
]


def _expand_keywords(term: str) -> list[str]:
    """把用户词扩成同义词组；没命中任何组就按原词查。

    用「包含」而不是「等于」，所以模型传进来一句「哪些实验室有显卡」也能命中。
    """
    if not term:
        return []
    for group in SYNONYM_GROUPS:
        if any(word in term for word in group):
            return group
    return [term]


def search_equipment(db: Session, keyword: str) -> str:
    """跨实验室搜索设备，返回每个设备所属实验室和当前可用数量。

    keyword 传具体硬件名或功能词，如：显卡、服务器、交换机、示波器、相机。
    available_now 是「当前时刻」的可用数量，不代表其他时间段。
    """
    term = (keyword or "").strip().lower()
    if not term:
        return json.dumps(
            {
                "ok": False,
                "retryable": True,
                "message": "keyword 不能为空，请传入具体设备名，如：显卡",
            },
            ensure_ascii=False,
        )

    words = _expand_keywords(term)
    patterns = [f"%{word}%" for word in words]

    rows = (
        db.query(Equipment, Lab)
        .join(Lab, Equipment.lab_id == Lab.id)
        .filter(
            or_(
                *[Equipment.name.ilike(p) for p in patterns],
                *[Equipment.description.ilike(p) for p in patterns],
                *[Equipment.spec.ilike(p) for p in patterns],
            ),
            Equipment.status == 1,  # 只查状态正常的设备（排除维修中）
            Lab.status == 1,  # 只查开放中的实验室
        )
        .limit(30)
        .all()
    )

    if not rows:
        return json.dumps(
            {
                "ok": False,
                # 没匹配到不代表工具坏了，换个更通用的词还有机会
                "retryable": True,
                "message": f"没有找到与「{keyword}」匹配的设备，可以换个更通用的词，如显卡、服务器",
            },
            ensure_ascii=False,
        )

    # 一次查出这批设备的当前占用数，避免在循环里逐条查询（N+1）
    # 占用判定必须带时间窗：只看 status 会把「上周的预约」也算成现在被占着
    now = datetime.now()
    occupied_rows = (
        db.query(Reservation.equipment_id, func.count(Reservation.id))
        .filter(
            Reservation.equipment_id.in_([eq.id for eq, _ in rows]),
            Reservation.status.in_([0, 1]),  # 0待审核 1已通过
            Reservation.date == now.date(),
            Reservation.start_time <= now.time(),
            Reservation.end_time > now.time(),
        )
        .group_by(Reservation.equipment_id)
        .all()
    )
    occupied_map = {equipment_id: count for equipment_id, count in occupied_rows}

    equipments = []
    for eq, lab in rows:
        occupied = occupied_map.get(eq.id, 0)
        equipments.append(
            {
                "lab_id": lab.id,
                "lab_name": lab.name,
                "location": lab.location,
                "open_time": (
                    f"{lab.open_time}-{lab.close_time}" if lab.open_time else None
                ),
                "equipment_id": eq.id,
                "equipment_name": eq.name,
                "spec": eq.spec,
                "total_quantity": eq.quantity,
                # 注意：available_now=0 的设备也要返回，让模型知道「有这个设备但被占用了」
                "available_now": max(eq.quantity - occupied, 0),
            }
        )

    return json.dumps(
        {
            "ok": True,
            "count": len(equipments),
            # 把实际用到的同义词回传给模型，方便它解释「我按显卡/GPU/A100 搜的」
            "keywords": words,
            "note": "available_now 是当前时刻的可用数量，其他时间段需要另行确认",
            "equipments": equipments,
        },
        ensure_ascii=False,
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
