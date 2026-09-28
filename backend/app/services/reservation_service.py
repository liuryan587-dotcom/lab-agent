from sqlalchemy.orm import Session
from datetime import datetime
from app.common.exceptions import BusinessException
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest, ReservationResponse
from app.common.response import PageResponse


def create_reservation(db: Session, current_user: User, data: ReservationCreateRequest):
    """创建预约记录"""
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    # 将当前时间也转换为 time 对象，方便后续比较
    current_time = datetime.strptime(now.strftime("%H:%M"), "%H:%M").time()

    # 1. 先查询实验室（必须在解析 lab.open_time 之前）
    lab = db.query(Lab).filter(Lab.id == data.lab_id).first()
    if not lab:
        raise BusinessException(code=400, message="实验室不存在")
    if lab.status != 1:
        raise BusinessException(code=400, message="实验室已关闭")

    # 2. 解析各种时间（统一转换为 time 对象）
    try:
        req_start_time = datetime.strptime(data.start_time, "%H:%M").time()
        req_end_time = datetime.strptime(data.end_time, "%H:%M").time()
        lab_open_time = datetime.strptime(lab.open_time, "%H:%M").time()
        lab_close_time = datetime.strptime(lab.close_time, "%H:%M").time()
    except ValueError:
        raise BusinessException(code=400, message="时间格式错误，应为 HH:MM")

    # 3. 时间逻辑校验（此时都是 time 对象，比较安全）
    if data.date < current_date:
        raise BusinessException(code=400, message="预约日期不能小于当前的日期")
    if req_end_time < req_start_time:
        raise BusinessException(code=400, message="预约时间的结束时间不能小于开始时间")
    if data.date == current_date and req_start_time < current_time:
        raise BusinessException(code=400, message="预约开始时间不能小于当前的时间")
    if lab.open_time and req_start_time < lab_open_time:
        raise BusinessException(code=400, message="预约时间不能早于实验室的开放时间")
    if lab.close_time and req_end_time > lab_close_time:
        raise BusinessException(code=400, message="预约时间不能晚于实验室的关闭时间")

    # equipment_id 不为空 则表示这次是预约的实验室设备
    if data.equipment_id:
        equipment = (
            db.query(Equipment).filter(Equipment.id == data.equipment_id).first()
        )
        if not equipment:
            raise BusinessException(code=400, message="实验室设备不存在")
        if equipment.status != 1:
            raise BusinessException(code=400, message="实验室设备正在维修")

    # 4. 数据库冲突查询（将 time 对象转回字符串，因为数据库存的是 VARCHAR）
    # 转回 "HH:MM" 格式，带前导零，例如 "09:30"
    db_start_time_str = req_start_time.strftime("%H:%M")
    db_end_time_str = req_end_time.strftime("%H:%M")

    query = db.query(Reservation).filter(
        Reservation.lab_id == data.lab_id,
        Reservation.date == data.date,
        Reservation.status.in_([0, 1]),  # 0待审核 1已通过
        Reservation.start_time < db_end_time_str,  # 使用标准化的字符串去查数据库
        Reservation.end_time > db_start_time_str,
    )
    if data.equipment_id:
        query = query.filter(Reservation.equipment_id == data.equipment_id)
    else:
        query = query.filter(Reservation.equipment_id.is_(None))

    res = query.first()
    if res:
        raise BusinessException(code=400, message="该时段已预约")

    # 5. 保存记录（修正了变量名拼写错误）
    reservation_model = Reservation(
        user_id=current_user.id,
        lab_id=data.lab_id,
        equipment_id=data.equipment_id,
        date=data.date,
        start_time=data.start_time,  # 存进去的依然是原始字符串
        end_time=data.end_time,
        remark=data.remark,
        status=0,
    )
    db.add(reservation_model)
    db.commit()
    db.refresh(reservation_model)  # 如果需要返回这条记录的 ID，建议加上这行
    return reservation_model  # 建议返回创建的对象


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
