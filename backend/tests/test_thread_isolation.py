#!/usr/bin/env python
"""会话隔离（横向越权）回归测试 —— 不依赖 pytest。

跑法（在 backend 目录下）：

    .\\.venv\\Scripts\\python.exe tests\\test_thread_isolation.py

覆盖的是「拿着别人的 thread_id 去读」这条路径：

1. 自己读自己的会话 → 正常拿到（正向对照，防止测试本身失效）
2. B 拿 A 的 thread_id 读消息 → 空
3. B 拿 A 的 thread_id 读界面消息 → 空
4. latest_thread_id 只在自己名下找，不会返回别人的 thread
5. B 拿 A 的 thread_id 读待确认单 → 空

为什么单独写这个文件：评估集跑的是「模型答得对不对」，
跑不到「换个人来读能不能读走」；这条是数据边界，必须在代码层验证。
"""

import os
import pathlib
import sys
import tempfile

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "tests" / "eval"))

# 必须在 import app.* 之前设置：config 在模块加载时就会读它
DB_PATH = (
    pathlib.Path(tempfile.gettempdir()) / f"lab-agent-thread-test-{os.getpid()}.db"
)
if DB_PATH.exists():
    try:
        DB_PATH.unlink()
    except PermissionError:
        DB_PATH = (
            pathlib.Path(tempfile.gettempdir())
            / f"lab-agent-thread-test-{os.getpid()}-retry.db"
        )
os.environ.setdefault("DATABASE_URL", "sqlite:///" + DB_PATH.as_posix())

import seed  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import chat_history_service, pending_action_service  # noqa: E402

TESTS = []
THREAD = "thread-shared-001"


def test(fn):
    TESTS.append(fn)
    return fn


test.__test__ = False


# --------------------------------------------------------------------- helpers
def fresh():
    """每条用例都从干净的库开始。"""
    seed.reset()
    db = SessionLocal()
    owner = db.query(User).filter(User.username == seed.STUDENT_USERNAME).one()
    other = db.query(User).filter(User.username == "eval_admin").one()
    return db, owner, other


def seed_one_round(db, owner):
    """owner 在 THREAD 里留下一轮对话。"""
    chat_history_service.append_messages(
        db,
        THREAD,
        owner.id,
        [
            HumanMessage(content="人工智能实验室有什么设备？"),
            AIMessage(content="有一台 RTX5090。"),
        ],
    )


# --------------------------------------------------------------------- cases
@test
def test_owner_can_read_own_thread():
    """正向对照：如果这条不过，说明测试环境本身有问题。"""
    db, owner, _ = fresh()
    try:
        seed_one_round(db, owner)
        messages = chat_history_service.load_messages(db, THREAD, owner.id)
        assert len(messages) == 2, f"本人应读到 2 条，实际 {len(messages)}"
    finally:
        db.close()


@test
def test_other_user_cannot_read_messages():
    """核心断言：横向越权。"""
    db, owner, other = fresh()
    try:
        seed_one_round(db, owner)
        leaked = chat_history_service.load_messages(db, THREAD, other.id)
        assert leaked == [], f"拿到别人的会话了，泄漏 {len(leaked)} 条"
    finally:
        db.close()


@test
def test_other_user_cannot_read_display_messages():
    db, owner, other = fresh()
    try:
        seed_one_round(db, owner)
        leaked = chat_history_service.list_display_messages(db, THREAD, other.id)
        assert leaked == [], f"界面接口泄漏了别人的会话：{leaked}"
    finally:
        db.close()


@test
def test_latest_thread_id_is_scoped_by_user():
    db, owner, other = fresh()
    try:
        seed_one_round(db, owner)
        assert chat_history_service.latest_thread_id(db, owner.id) == THREAD
        assert (
            chat_history_service.latest_thread_id(db, other.id) is None
        ), "别人的最近会话被当成了自己的"
    finally:
        db.close()


@test
def test_other_user_cannot_list_pending_by_thread():
    db, owner, other = fresh()
    try:
        pending_action_service.create_pending(
            db,
            owner.id,
            "create_lab_reservation",
            {
                "lab_id": 4,
                "equipment_id": None,
                "date": "2030-01-01",
                "start_time": "14:00",
                "end_time": "16:00",
                "remark": None,
            },
            thread_id=THREAD,
        )
        assert (
            pending_action_service.list_by_thread(db, other.id, THREAD) == []
        ), "读到别人的待确认单"
        assert len(pending_action_service.list_by_thread(db, owner.id, THREAD)) == 1
    finally:
        db.close()


# --------------------------------------------------------------------- runner
if __name__ == "__main__":
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
