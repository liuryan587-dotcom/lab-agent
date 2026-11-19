"""给「当前 DATABASE_URL 指向的库」灌一套演示数据。

和 scripts/seed_demo.py 的区别：
- seed_demo.py 硬编码 SQLite，只服务本地演示，不碰配置里的库
- 这个脚本走 `settings.DATABASE_URL`，所以：
    * 在容器里跑 → 写 compose 里的 MySQL
    * 在本地跑   → 写 backend/.env 里的库（谨慎！）

用法（容器里）：
    docker compose exec backend uv run python scripts/seed_mysql.py

    注意：容器里的 `python` 默认是系统解释器，没有装依赖；
    依赖在 /app/.venv 里，必须用 `uv run` 进入那个环境。
    如果 Dockerfile 里把 /app/.venv/bin 加进了 PATH，才可以省略 uv run。

保护：
- 库里已经有用户时直接退出，不会重复插入
- 打印目标库地址（密码打码），避免灌错地方
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, time, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.exc import IntegrityError, OperationalError  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.equipment import Equipment  # noqa: E402
from app.models.lab import Lab  # noqa: E402
from app.models.reservation import Reservation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.utils.password import hash_password  # noqa: E402

DEMO_PASSWORD = "Demo123456!"


def mask(url: str) -> str:
    """把 URL 里的密码换成 ***，避免日志或截图泄露。"""
    if "@" not in url or "://" not in url:
        return url
    head, tail = url.rsplit("@", 1)
    scheme, creds = head.split("://", 1)
    if ":" not in creds:
        return url
    return f"{scheme}://{creds.split(':', 1)[0]}:***@{tail}"


def seed() -> None:
    db = SessionLocal()
    try:
        try:
            existing = db.query(User).count()
        except OperationalError:
            print("表还不存在。先跑迁移（容器启动时会自动执行 alembic upgrade head）。")
            raise SystemExit(1)

        if existing > 0:
            print(f"库里已经有 {existing} 个用户，停止灌数据，避免重复。")
            print("要从零开始：docker compose down -v  然后重新启动。")
            raise SystemExit(1)

        admin = User(
            username="demo_admin",
            password=hash_password(DEMO_PASSWORD),
            name="演示管理员",
            role="admin",
            status=1,
        )
        student = User(
            username="demo_student",
            password=hash_password(DEMO_PASSWORD),
            name="演示学生",
            role="student",
            status=1,
        )
        db.add_all([admin, student])
        db.flush()

        ai_lab = Lab(
            name="人工智能实验室",
            location="A 楼 301",
            capacity=30,
            open_time="08:00",
            close_time="22:00",
            description="用于机器学习、深度学习和大模型实验。",
            status=1,
        )
        computer_lab = Lab(
            name="计算机实验室",
            location="B 楼 205",
            capacity=50,
            open_time="09:00",
            close_time="21:00",
            description="提供通用计算机和图形计算设备。",
            status=1,
        )
        db.add_all([ai_lab, computer_lab])
        db.flush()

        gpu = Equipment(
            lab_id=ai_lab.id,
            name="GPU 工作站",
            spec="RTX 5090 32GB",
            quantity=4,
            description="用于深度学习训练和推理。",
            status=1,
        )
        server = Equipment(
            lab_id=ai_lab.id,
            name="高性能服务器",
            spec="双路 Xeon · 256GB RAM",
            quantity=2,
            description="用于多用户实验和模型部署。",
            status=1,
        )
        workstation = Equipment(
            lab_id=computer_lab.id,
            name="图形工作站",
            spec="RTX 4090 24GB",
            quantity=10,
            description="用于计算机视觉与图形学实验。",
            status=1,
        )
        db.add_all([gpu, server, workstation])
        db.flush()

        # 两条明天的预约：让「可约时段」和「冲突校验」一上来就有东西可看
        tomorrow = date.today() + timedelta(days=1)
        db.add_all(
            [
                Reservation(
                    user_id=student.id,
                    lab_id=ai_lab.id,
                    date=tomorrow,
                    start_time=time(10, 0),
                    end_time=time(11, 0),
                    remark="演示：实验室预约",
                    status=1,
                ),
                Reservation(
                    user_id=student.id,
                    lab_id=computer_lab.id,
                    equipment_id=workstation.id,
                    date=tomorrow,
                    start_time=time(14, 0),
                    end_time=time(15, 0),
                    remark="演示：设备预约",
                    status=1,
                ),
            ]
        )

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            print(f"写入失败（可能是用户名已存在）：{exc.orig}")
            raise SystemExit(1)

        print("演示数据已写入：")
        print("  实验室   2 个（人工智能实验室 / 计算机实验室）")
        print("  设备     3 台")
        print(f"  预约     2 条（{tomorrow.isoformat()} 10:00 实验室 / 14:00 设备）")
        print()
        print(f"  学生    demo_student / {DEMO_PASSWORD}")
        print(f"  管理员  demo_admin   / {DEMO_PASSWORD}")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="给当前 DATABASE_URL 灌演示数据")
    parser.parse_args()

    print(f"目标库：{mask(settings.DATABASE_URL)}")
    seed()


if __name__ == "__main__":
    main()
