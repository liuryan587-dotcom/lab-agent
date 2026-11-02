"""待确认单：Agent 的写操作只落这一张表，落库要等用户点确认。"""

import json
import logging
from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from sqlalchemy.orm import Session

from app.common.exceptions import BusinessException
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.pending_action import (
    STATUS_CANCELLED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
    PendingAction,
)
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest
from app.services import chat_history_service, reservation_service

logger = logging.getLogger(__name__)

# 待确认单的有效期。太短用户来不及确认，太长会让「过期信息」的风险变大
PENDING_TTL_SECONDS = 300


def create_pending(
    db: Session,
    user_id: int,
    tool_name: str,
    payload: dict,
    thread_id: str | None = None,
) -> PendingAction:
    """生成一条待确认记录。注意：这里不碰业务表。"""
    action = PendingAction(
        user_id=user_id,
        thread_id=thread_id,
        tool_name=tool_name,
        payload=json.dumps(payload, ensure_ascii=False, default=str),
        status=STATUS_PENDING,
        expire_at=datetime.now() + timedelta(seconds=PENDING_TTL_SECONDS),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def _payload_of(action: PendingAction) -> dict:
    try:
        return json.loads(action.payload)
    except (TypeError, ValueError):
        return {}


def serialize(db: Session, action: PendingAction) -> dict:
    """给前端渲染确认卡片用的扁平结构，把 lab / equipment 名字一起带上。"""
    payload = _payload_of(action)

    lab_name = None
    lab_id = payload.get("lab_id")
    if lab_id:
        lab = db.get(Lab, lab_id)
        lab_name = lab.name if lab else None

    equipment_name = None
    equipment_id = payload.get("equipment_id")
    if equipment_id:
        equipment = db.get(Equipment, equipment_id)
        equipment_name = equipment.name if equipment else None

    return {
        "id": action.id,
        "status": action.status,
        "tool_name": action.tool_name,
        "expire_at": action.expire_at.isoformat(timespec="seconds"),
        "lab_id": lab_id,
        "lab_name": lab_name,
        "equipment_id": equipment_id,
        "equipment_name": equipment_name,
        "date": payload.get("date"),
        "start_time": payload.get("start_time"),
        "end_time": payload.get("end_time"),
        "remark": payload.get("remark"),
    }


def list_pending(db: Session, user_id: int) -> list[dict]:
    expire_stale(db, user_id)
    actions = (
        db.query(PendingAction)
        .filter(
            PendingAction.user_id == user_id,
            PendingAction.status == STATUS_PENDING,
        )
        .order_by(PendingAction.id.desc())
        .all()
    )
    return [serialize(db, action) for action in actions]


def list_by_thread(db: Session, user_id: int, thread_id: str) -> list[dict]:
    """某个会话里还没确认的卡片。刷新页面后要用它把卡片恢复出来。"""
    if not thread_id:
        return []
    expire_stale(db, user_id)
    actions = (
        db.query(PendingAction)
        .filter(
            PendingAction.user_id == user_id,
            PendingAction.thread_id == thread_id,
            PendingAction.status == STATUS_PENDING,
        )
        .order_by(PendingAction.id.desc())
        .all()
    )
    return [serialize(db, action) for action in actions]


def expire_stale(db: Session, user_id: int | None = None) -> None:
    """把过期未确认的单子标成 3，避免列表里一直挂着。"""
    query = db.query(PendingAction).filter(
        PendingAction.status == STATUS_PENDING,
        PendingAction.expire_at < datetime.now(),
    )
    if user_id is not None:
        query = query.filter(PendingAction.user_id == user_id)
    stale = query.all()
    if not stale:
        return
    for action in stale:
        action.status = STATUS_EXPIRED
    db.commit()


def _load_owned(db: Session, user_id: int, action_id: int) -> PendingAction:
    action = db.get(PendingAction, action_id)
    if action is None:
        raise BusinessException(code=404, message="待确认记录不存在")
    # 越权确认别人的单子：这是安全边界，必须在代码里挡
    if action.user_id != user_id:
        raise BusinessException(code=403, message="无权操作他人的待确认记录")
    return action


def confirm(db: Session, user_id: int, action_id: int):
    """执行待确认的预约。

    注意这里会**重新跑一遍** reservation_service 的全部业务校验：
    从生成待确认单到用户点确认之间，实验室可能被关闭、时段可能被别人订走。
    用模型当时看到的数据直接落库就是 TOCTOU 漏洞。
    """
    action = _load_owned(db, user_id, action_id)

    if action.status != STATUS_PENDING:
        raise BusinessException(code=400, message="该操作已处理，不能再确认")
    if action.expire_at < datetime.now():
        action.status = STATUS_EXPIRED
        db.commit()
        raise BusinessException(code=400, message="确认已过期，请重新发起预约")

    payload = _payload_of(action)
    try:
        data = ReservationCreateRequest(**payload)
    except Exception as exc:
        raise BusinessException(code=400, message=f"待确认记录的参数已失效: {exc}")

    user = db.get(User, user_id)
    if user is None:
        raise BusinessException(code=401, message="用户不存在，请重新登录")

    reservation = reservation_service.create_reservation(db, user, data)

    action.status = STATUS_EXECUTED
    action.executed_reservation_id = reservation.id
    db.commit()

    # 把「已提交」写回会话历史。否则下一轮模型还以为这单没成，
    # 会重新发起同一个时段，然后撞上自己刚创建的这条。
    if action.thread_id:
        try:
            chat_history_service.append_messages(
                db,
                action.thread_id,
                user_id,
                [
                    AIMessage(
                        content=(
                            f"（已确认并提交：预约号 #{reservation.id}，状态待审核）"
                        )
                    )
                ],
            )
        except Exception:
            logger.exception("把确认结果写回会话历史失败（不影响预约本身）")

    return reservation


def cancel(db: Session, user_id: int, action_id: int) -> None:
    action = _load_owned(db, user_id, action_id)
    if action.status != STATUS_PENDING:
        raise BusinessException(code=400, message="该操作已处理，不能再取消")
    action.status = STATUS_CANCELLED
    db.commit()
