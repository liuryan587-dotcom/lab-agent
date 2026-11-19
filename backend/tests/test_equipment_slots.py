"""设备可约时段：独占资源 + 清理时间。

和实验室（计数型）的区别都锁在这里：
- capacity 固定 1：有预约就是不能约，不看容量
- 默认 buffer=10：两段之间要留清理时间
- 开放时间取自设备所属实验室
"""

from datetime import date, time, timedelta

import pytest

from app.common.exceptions import BusinessException
from app.database import Base, SessionLocal, engine
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.reservation import Reservation
from app.models.user import User
from app.services.reservation_service import get_equipment_free_starts

TOMORROW = date.today() + timedelta(days=1)


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    lab = Lab(
        name="设备测试实验室",
        capacity=5,
        open_time="08:00",
        close_time="21:00",
        status=1,
    )
    user = User(
        username="equipment-test",
        password="hashed",
        name="测试用户",
        role="student",
        status=1,
    )
    session.add_all([lab, user])
    session.commit()
    session.refresh(lab)
    session.refresh(user)
    equipment = Equipment(lab_id=lab.id, name="测试显卡", quantity=1, status=1)
    session.add(equipment)
    session.commit()
    session.refresh(equipment)
    try:
        yield session, lab, user, equipment
    finally:
        session.close()


def book(session, lab, user, equipment, start, end):
    session.add(
        Reservation(
            user_id=user.id,
            lab_id=lab.id,
            equipment_id=equipment.id,
            date=TOMORROW,
            start_time=start,
            end_time=end,
            status=1,
        )
    )
    session.commit()


def test_reserved_slot_is_excluded(db):
    session, lab, user, equipment = db
    book(session, lab, user, equipment, time(10, 0), time(11, 0))

    slots = get_equipment_free_starts(session, equipment.id, TOMORROW)["slots"]

    assert 600 not in slots  # 10:00 已被占
    assert 660 not in slots  # 11:00 紧贴，默认 buffer=10 不够
    assert 670 in slots      # 11:10 间距正好 10 分钟


def test_open_hours_come_from_lab(db):
    session, _, _, equipment = db

    slots = get_equipment_free_starts(session, equipment.id, TOMORROW)["slots"]

    assert slots[0] == 480          # 08:00 开门
    assert slots[-1] + 60 <= 1260   # 21:00 关门


def test_equipment_under_repair_raises_400(db):
    session, _, _, equipment = db
    equipment.status = 0  # 维修中
    session.commit()

    with pytest.raises(BusinessException) as exc:
        get_equipment_free_starts(session, equipment.id, TOMORROW)

    assert exc.value.code == 400


def test_missing_equipment_raises_404(db):
    session, _, _, _ = db

    with pytest.raises(BusinessException) as exc:
        get_equipment_free_starts(session, 99999, TOMORROW)

    assert exc.value.code == 404
