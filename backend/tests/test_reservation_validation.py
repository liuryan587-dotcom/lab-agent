"""Reservation business-rule tests.

Run with:
    .venv/Scripts/python.exe -m pytest tests/test_reservation_validation.py -q
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.common.exceptions import BusinessException  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.lab import Lab  # noqa: E402
from app.models.reservation import Reservation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.reservation import ReservationCreateRequest  # noqa: E402
from app.services.reservation_service import (  # noqa: E402
    create_reservation,
    validate_reservation,
)


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    lab = Lab(
        name="测试实验室",
        capacity=20,
        open_time="08:00",
        close_time="22:00",
        status=1,
    )
    user = User(
        username="reservation-test",
        password="hashed",
        name="测试用户",
        role="student",
        status=1,
    )
    session.add_all([lab, user])
    session.commit()
    session.refresh(lab)
    session.refresh(user)
    try:
        yield session, lab, user
    finally:
        session.close()


def request(lab_id: int, *, start="10:00", end="11:00"):
    return ReservationCreateRequest(
        lab_id=lab_id,
        date=(date.today() + timedelta(days=1)).isoformat(),
        start_time=start,
        end_time=end,
    )


def raises_message(message, fn):
    with pytest.raises(BusinessException) as exc_info:
        fn()
    assert exc_info.value.message == message


def test_create_and_overlap_are_rejected(db):
    session, lab, user = db
    create_reservation(session, user, request(lab.id))
    raises_message(
        "该时段已预约", lambda: validate_reservation(session, request(lab.id))
    )


def test_opening_hours_are_enforced(db):
    session, lab, _ = db
    raises_message(
        "预约时间不能早于实验室的开放时间",
        lambda: validate_reservation(
            session, request(lab.id, start="07:00", end="08:30")
        ),
    )


def test_invalid_time_range_is_rejected(db):
    session, lab, _ = db
    raises_message(
        "预约时间的结束时间不能小于开始时间",
        lambda: validate_reservation(
            session, request(lab.id, start="12:00", end="11:00")
        ),
    )
