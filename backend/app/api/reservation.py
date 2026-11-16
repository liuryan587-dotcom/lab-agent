from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import date
from app.common.response import Response
from app.database import get_db
from app.dependencies.auth import get_current_user, get_current_admin
from app.models.reservation import Reservation
from app.models.user import User
from app.models.lab import Lab
from app.schemas.reservation import ReservationCreateRequest, AuditReservationRequest
from app.services import reservation_service
from datetime import datetime

router = APIRouter(prefix="/reservation", tags=["预约相关接口"])


@router.get("/list")
def get_reservation_page_list(
    page: int = 1,
    page_size: int = 10,
    status: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    res = reservation_service.get_reservation_page_list(
        db, current_user, page, page_size, status
    )
    return Response.success(data=res)


@router.get("/starts")
def get_reservation_starts(
    lab_id: int,
    day: date,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    slot_duration: int = 60,
    step: int = 10,
    buffer: int = 0,
):
    rows = (
        db.query(Reservation)
        .filter(
            Reservation.lab_id == lab_id,
            Reservation.date == day,
            Reservation.status != 2,
            Reservation.status != 3,
        )
        .all()
    )
    EXISTING = [
        (
            row.start_time.hour * 60 + row.start_time.minute,
            row.end_time.hour * 60 + row.end_time.minute,
        )
        for row in rows
    ]
    lab = db.query(Lab).filter(Lab.id == lab_id).first()
    capacity = lab.capacity
    open_start = reservation_service.to_minutes(lab.open_time)
    open_end = reservation_service.to_minutes(lab.close_time)
    earliest = open_start
    if day == date.today():
        now = datetime.now()
        earliest = now.hour * 60 + now.minute
    res = reservation_service.find_free_slots(
        existing=EXISTING,
        open_start=open_start,
        open_end=open_end,
        duration=slot_duration,
        step=step,
        buffer=buffer,
        capacity=capacity,
        earliest=earliest,
    )

    return Response.success(data=res)


@router.put("/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation_service.cancel_reservation(db, current_user, reservation_id)
    return Response.success()


@router.put("/{reservation_id}/audit")
def audit_reservation(
    reservation_id: int,
    data: AuditReservationRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    reservation_service.audit_reservation(db, reservation_id, data.status)
    return Response.success()


@router.post("")
def create_reservation(
    data: ReservationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    reservation_service.create_reservation(db, current_user, data)
    return Response.success()
