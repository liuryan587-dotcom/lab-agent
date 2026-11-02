import logging
import traceback

from sqlalchemy.orm import Session
from datetime import datetime
from app.common.exceptions import BusinessException
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest, ReservationResponse
from app.common.response import PageResponse
import asyncio
from app.database import SessionLocal

# 注意：from fastapi import logger 拿到的是「模块」而不是 logger 实例，
# 调用 logger.exception() 会抛 AttributeError，反而把真实异常顶掉、掩盖故障原因
logger = logging.getLogger(__name__)


def validate_reservation(db: Session, data: ReservationCreateRequest) -> dict:
    """跑完所有业务校验，返回解析好的 date / time 字段。

    抽出来是为了「待确认单」：
      - 生成待确认记录时先跑一遍，避免让用户确认一个注定失败的预约
      - 用户点确认时再跑一遍，防止两次之间数据变了（TOCTOU）
    任何一条不满足都抛 BusinessException。
    """
    now = datetime.now()
    current_date = now.date()  # date 对象，和 DATE 列同类型比较
    # 将当前时间也转换为 time 对象（截到分钟），和 TIME 列同类型比较
    current_time = datetime.strptime(now.strftime("%H:%M"), "%H:%M").time()

    # 1. 先查询实验室（必须在解析 lab.open_time 之前）
    lab = db.query(Lab).filter(Lab.id == data.lab_id).first()
    if not lab:
        raise BusinessException(code=400, message="实验室不存在")
    if lab.status != 1:
        raise BusinessException(code=400, message="实验室已关闭")

    # 2. 解析日期与时间（统一转成 date / time 对象，与数据库列类型保持一致）
    try:
        req_date = datetime.strptime(data.date, "%Y-%m-%d").date()
    except ValueError:
        raise BusinessException(code=400, message="日期格式错误，应为 YYYY-MM-DD")

    try:
        req_start_time = datetime.strptime(data.start_time, "%H:%M").time()
        req_end_time = datetime.strptime(data.end_time, "%H:%M").time()
    except ValueError:
        raise BusinessException(code=400, message="时间格式错误，应为 HH:MM")

    # 实验室的开放/关闭时间在模型里是 nullable，为空表示不限制。
    # 注意 strptime(None, ...) 抛的是 TypeError 而不是 ValueError，
    # 所以必须先判空再解析，否则会穿透上面的 except 一路变成 500
    try:
        lab_open_time = (
            datetime.strptime(lab.open_time, "%H:%M").time() if lab.open_time else None
        )
        lab_close_time = (
            datetime.strptime(lab.close_time, "%H:%M").time()
            if lab.close_time
            else None
        )
    except ValueError:
        raise BusinessException(code=400, message="实验室开放时间格式错误，应为 HH:MM")

    # 3. 时间逻辑校验（此时都是 date / time 对象，比较安全）
    if req_date < current_date:
        raise BusinessException(code=400, message="预约日期不能小于当前的日期")
    if req_end_time < req_start_time:
        raise BusinessException(code=400, message="预约时间的结束时间不能小于开始时间")
    if req_date == current_date and req_start_time < current_time:
        raise BusinessException(code=400, message="预约开始时间不能小于当前的时间")
    if lab_open_time and req_start_time < lab_open_time:
        raise BusinessException(code=400, message="预约时间不能早于实验室的开放时间")
    if lab_close_time and req_end_time > lab_close_time:
        raise BusinessException(code=400, message="预约时间不能晚于实验室的关闭时间")

    # equipment_id 不为空 则表示这次是预约的实验室设备
    equipment = None
    if data.equipment_id:
        equipment = (
            db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
        )
        if not equipment:
            raise BusinessException(code=400, message="实验室设备不存在")
        if equipment.status != 1:
            raise BusinessException(code=400, message="实验室设备正在维修")

    # 4. 数据库冲突查询
    # date / start_time / end_time 现在是 DATE / TIME 列，
    # 直接用 date / time 对象交给 MySQL 按真实时间语义判断重叠，不再拼字符串
    # 重叠条件：已有.start < 新.end 且 已有.end > 新.start
    query = db.query(Reservation).filter(
        Reservation.lab_id == data.lab_id,
        Reservation.date == req_date,
        Reservation.status.in_([0, 1]),  # 0待审核 1已通过
        Reservation.start_time < req_end_time,
        Reservation.end_time > req_start_time,
    )
    if data.equipment_id:
        query = query.filter(Reservation.equipment_id == data.equipment_id)
    else:
        query = query.filter(Reservation.equipment_id.is_(None))

    if query.first():
        raise BusinessException(code=400, message="该时段已预约")

    return {
        "date": req_date,
        "start_time": req_start_time,
        "end_time": req_end_time,
        "equipment": equipment,
    }


def create_reservation(db: Session, current_user: User, data: ReservationCreateRequest):
    """创建预约记录（会完整跑一遍业务校验，确认接口也走这里）"""
    parsed = validate_reservation(db, data)

    # 保存记录（存 date / time 对象，和 DATE / TIME 列类型一致）
    reservation_model = Reservation(
        user_id=current_user.id,
        lab_id=data.lab_id,
        equipment_id=data.equipment_id,
        date=parsed["date"],
        start_time=parsed["start_time"],
        end_time=parsed["end_time"],
        remark=data.remark,
        status=0,
    )
    try:
        db.add(reservation_model)
        db.commit()
        db.refresh(reservation_model)  # 如果需要返回这条记录的 ID，建议加上这行
        return reservation_model  # 建议返回创建的对象
    except BusinessException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("创建预约失败")
        raise BusinessException(code=400, message="预约失败,请稍后再试")


def get_reservation_page_list(
    db: Session,
    current_user: User,
    page: int,
    page_size: int,
    status: int | None = None,
):
    """查询预约的记录"""
    query = db.query(Reservation)
    if current_user.role != "admin":
        query = query.filter(Reservation.user_id == current_user.id)
    if status is not None:
        query = query.filter(Reservation.status == status)
    total = query.count()
    items = (
        query.order_by(Reservation.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    result = []
    for item in items:
        res = ReservationResponse.model_validate(item)
        res.user_name = item.user.name if item.user else None
        res.lab_name = item.lab.name if item.lab else None
        res.equipment_name = item.equipment.name if item.equipment else None
        res.type = "设备" if item.equipment_id else "实验室"
        result.append(res)

    return PageResponse(list=result, total=total)


def cancel_reservation(db: Session, current_user: User, reservation_id: int):
    """学生取消预约"""
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.user_id != current_user.id:
        raise BusinessException(message="无权限", code=403)
    if item.status != 0:
        raise BusinessException(message="当前状态无法取消")
    item.status = 3
    db.commit()


def audit_reservation(db: Session, reservation_id: int, status: int):
    """管理员审核预约"""
    if status not in [1, 2]:
        raise BusinessException(message="审核状态错误")
    item = db.query(Reservation).filter(Reservation.id == reservation_id).first()
    if not item:
        raise BusinessException(message="预约记录不存在")
    if item.status != 0:
        raise BusinessException(message="当前状态不支持审核")
    item.status = status
    db.commit()


def expire_pending_reservations():
    db = SessionLocal()
    try:
        now = datetime.now()
        # date / start_time / end_time 现在是 DATE / TIME 列，
        # 取出来是 date / time 对象，必须用同类型比较（原来是拿字符串比，会 TypeError）
        today = now.date()
        now_time = datetime.strptime(now.strftime("%H:%M"), "%H:%M").time()
        items = db.query(Reservation).filter(Reservation.status == 0).all()
        changed = False
        for item in items:
            if item.date < today or (item.date == today and item.end_time <= now_time):
                item.status = 3
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()


async def run_expire_scan():
    while True:
        expire_pending_reservations()
        await asyncio.sleep(60)
