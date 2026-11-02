"""Create a self-contained SQLite database for local demos.

Usage (from backend/):
    .venv/Scripts/python.exe scripts/seed_demo.py
    .venv/Scripts/python.exe scripts/seed_demo.py --reset

The script deliberately does not touch the configured MySQL database. It writes
backend/data/demo.db, which is ignored by Git.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = BACKEND_ROOT / "data" / "demo.db"
sys.path.insert(0, str(BACKEND_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the local lab-agent demo database")
    parser.add_argument("--reset", action="store_true", help="delete the existing demo database first")
    args = parser.parse_args()

    if args.reset and DB_PATH.exists():
        DB_PATH.unlink()
    elif DB_PATH.exists():
        import sqlite3

        with sqlite3.connect(DB_PATH) as connection:
            versioned = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
            ).fetchone()
        if not versioned:
            print(f"Legacy demo database: {DB_PATH}")
            print("Use --reset to recreate this disposable demo database with Alembic.")
            return

    # Set these before importing app modules; Settings reads environment values
    # at import time. Dummy model values are enough for CRUD demos; AI chat still
    # needs a real compatible provider configured in backend/.env.
    os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
    os.environ.setdefault("JWT_SECRET_KEY", "local-demo-secret-change-me")
    os.environ.setdefault("LLM_API_KEY", "demo-key")
    os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    os.environ.setdefault("LLM_MODEL", "qwen2.5:7b")

    from app.database import SessionLocal
    from app.models.equipment import Equipment
    from app.models.lab import Lab
    from app.models.user import User
    from app.utils.password import hash_password

    import subprocess

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print(f"Demo database already contains data: {DB_PATH}")
            print("Use --reset to recreate it.")
            return

        admin = User(
            username="demo_admin",
            password=hash_password("Demo123456!"),
            name="演示管理员",
            role="admin",
            status=1,
        )
        student = User(
            username="demo_student",
            password=hash_password("Demo123456!"),
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

        db.add_all(
            [
                Equipment(
                    lab_id=ai_lab.id,
                    name="GPU 工作站",
                    spec="RTX 5090 32GB",
                    quantity=4,
                    description="用于深度学习训练和推理。",
                    status=1,
                ),
                Equipment(
                    lab_id=ai_lab.id,
                    name="高性能服务器",
                    spec="双路 Xeon · 256GB RAM",
                    quantity=2,
                    description="用于多用户实验和模型部署。",
                    status=1,
                ),
                Equipment(
                    lab_id=computer_lab.id,
                    name="图形工作站",
                    spec="RTX 4090 24GB",
                    quantity=10,
                    description="用于计算机视觉与图形学实验。",
                    status=1,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    print(f"Created demo database: {DB_PATH}")
    print("Student: demo_student / Demo123456!")
    print("Admin:   demo_admin   / Demo123456!")
    print(f"Demo reservation date: {(date.today() + timedelta(days=1)).isoformat()}")


if __name__ == "__main__":
    main()
