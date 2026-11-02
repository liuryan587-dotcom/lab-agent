#!/usr/bin/env python
"""待确认单的安全边界测试（不依赖 pytest）。

跑法（在 backend 目录下）：

    .\\.venv\\Scripts\\python.exe tests\\test_pending_action.py

覆盖 confirm / cancel 的几个安全分支——这些分支之前只有代码、从没被执行过：

1. 越权确认：A 生成的单子，B 不能确认（403）
2. 越权取消：同理（403）
3. 过期确认：超过 TTL 不能确认（400），状态变 3
4. 取消后确认：不能确认（400），状态保持 2
5. 重复确认：只能成功一次，预约只写一条
6. 正向路径：确认成功真的写进 reservations

为什么单独写这个文件：评估集只跑到「生成待确认单」，
真正决定数据会不会被写错的是 confirm 这一层。
"""

import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "tests" / "eval"))

# 必须在 import app.* 之前设置：config 在模块加载时就会读它
DB_PATH = pathlib.Path(tempfile.gettempdir()) / "lab-agent-pending-test.db"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()

import seed  # noqa: E402
from app.common.exceptions import BusinessException  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.pending_action import (  # noqa: E402
    STATUS_CANCELLED,
    STATUS_EXECUTED,
    STATUS_EXPIRED,
    STATUS_PENDING,
)
from app.models.reservation import Reservation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import pending_action_service  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# --------------------------------------------------------------------- helpers
def fresh():
    """每条用例都从干净的库开始。"""
    seed.reset()
    db = SessionLocal()
    student = db.query(User).filter(User.username == seed.STUDENT_USERNAME).one()
    admin = db.query(User).filter(User.username == "eval_admin").one()
    return db, student, admin


def make_pending(db, user, lab_id=4, start="14:00", end="16:00"):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    return pending_action_service.create_pending(
        db,
        user.id,
        "create_lab_reservation",
        {
            "lab_id": lab_id,
            "equipment_id": None,
            "date": tomorrow,
            "start_time": start,
            "end_time": end,
            "remark": None,
        },
        thread_id="t-test",
    )


def expect_error(code, fn):
    try:
        fn()
    except BusinessException as exc:
        assert exc.code == code, f"期望错误码 {code}，实际 {exc.code}（{exc.message}）"
        return exc
    raise AssertionError("期望抛出 BusinessException，但没有抛")


# --------------------------------------------------------------------- cases
@test
def test_confirm_happy_path():
    db, student, _ = fresh()
    try:
        action = make_pending(db, student)
        before = db.query(Reservation).count()

        reservation = pending_action_service.confirm(db, student.id, action.id)
        db.refresh(action)

        assert action.status == STATUS_EXECUTED, f"状态应变为已执行，实际 {action.status}"
        assert action.executed_reservation_id == reservation.id, "没把预约 id 回填到待确认单"
        assert db.query(Reservation).count() == before + 1, "确认后预约表没增加"
    finally:
        db.close()


@test
def test_cannot_confirm_others_action():
    """越权确认：这是安全边界，必须在代码里挡住。"""
    db, student, admin = fresh()
    try:
        action = make_pending(db, student)
        before = db.query(Reservation).count()

        expect_error(403, lambda: pending_action_service.confirm(db, admin.id, action.id))

        db.refresh(action)
        assert action.status == STATUS_PENDING, "被拒绝后状态不该变"
        assert db.query(Reservation).count() == before, "越权请求竟然写进了预约"
    finally:
        db.close()


@test
def test_cannot_cancel_others_action():
    db, student, admin = fresh()
    try:
        action = make_pending(db, student)

        expect_error(403, lambda: pending_action_service.cancel(db, admin.id, action.id))

        db.refresh(action)
        assert action.status == STATUS_PENDING, "被别人取消掉了"
    finally:
        db.close()


@test
def test_expired_action_cannot_be_confirmed():
    db, student, _ = fresh()
    try:
        action = make_pending(db, student)
        action.expire_at = datetime.now() - timedelta(seconds=1)
        db.commit()

        before = db.query(Reservation).count()
        expect_error(400, lambda: pending_action_service.confirm(db, student.id, action.id))

        db.refresh(action)
        assert action.status == STATUS_EXPIRED, f"过期单状态应变为 3，实际 {action.status}"
        assert db.query(Reservation).count() == before, "过期单竟然写进了预约"
    finally:
        db.close()


@test
def test_cancelled_action_cannot_be_confirmed():
    db, student, _ = fresh()
    try:
        action = make_pending(db, student)
        pending_action_service.cancel(db, student.id, action.id)
        db.refresh(action)
        assert action.status == STATUS_CANCELLED, "取消后状态应为 2"

        before = db.query(Reservation).count()
        expect_error(400, lambda: pending_action_service.confirm(db, student.id, action.id))
        assert db.query(Reservation).count() == before, "已取消的单子还能确认"
    finally:
        db.close()


@test
def test_double_confirm_writes_once():
    db, student, _ = fresh()
    try:
        action = make_pending(db, student)
        before = db.query(Reservation).count()

        pending_action_service.confirm(db, student.id, action.id)
        expect_error(400, lambda: pending_action_service.confirm(db, student.id, action.id))

        assert db.query(Reservation).count() == before + 1, "重复确认写了多条预约"
    finally:
        db.close()


# --------------------------------------------------------------------- runner
def main():
    passed = 0
    for fn in TESTS:
        name = fn.__name__
        try:
            fn()
            print(f"[PASS] {name}")
            passed += 1
        except AssertionError as exc:
            print(f"[FAIL] {name}: {exc}")
        except Exception as exc:  # 代码本身报错
            print(f"[ERROR] {name}: {type(exc).__name__}: {exc}")

    print()
    print(f"{passed}/{len(TESTS)} passed")
    return 0 if passed == len(TESTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
