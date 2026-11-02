"""评估集的种子数据。

为什么用固定 id：断言要稳定。自增 id 会随重置次数漂移，而评估集每次
reset 都重建库，写死 id 才能让样本里的「实验室 ID 4」永远指向人工智能实验室。

数据规模刻意做小：5 个实验室、7 台设备、1 条冲突预约，够覆盖五类样本即可。
"""

from datetime import datetime, time, timedelta

from app.database import Base, SessionLocal, engine
from app.models.agent_trace import AgentTrace, AgentTraceStep  # noqa: F401
from app.models.chat_message import ChatMessageRecord  # noqa: F401
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.pending_action import PendingAction  # noqa: F401  注册表结构
from app.models.reservation import Reservation
from app.models.user import User

STUDENT_USERNAME = "eval_student"


def reset() -> None:
    """丢弃并重建整个评估库。每条样本跑之前都会调用一次。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _seed(db)
        db.commit()
    finally:
        db.close()


def _seed(db) -> None:
    # 账号密码不参与评估（评估不走登录），填占位符即可
    db.add_all(
        [
            User(
                id=1,
                username="eval_admin",
                password="x",
                name="评估管理员",
                role="admin",
                status=1,
            ),
            User(
                id=2,
                username=STUDENT_USERNAME,
                password="x",
                name="评估学生",
                role="student",
                status=1,
            ),
        ]
    )

    db.add_all(
        [
            Lab(
                id=1,
                name="计算机实验室",
                location="志明楼101",
                capacity=60,
                open_time="08:00",
                close_time="21:00",
                status=1,
            ),
            Lab(
                id=2,
                name="化学实验室",
                location="志明楼205",
                capacity=30,
                open_time="08:30",
                close_time="18:00",
                status=1,
            ),
            Lab(
                id=3,
                name="物理实验室",
                location="志明楼301",
                capacity=40,
                open_time="08:00",
                close_time="20:00",
                status=1,
            ),
            Lab(
                id=4,
                name="人工智能实验室",
                location="志明楼218",
                capacity=12,
                open_time="08:30",
                close_time="21:30",
                status=1,
            ),
            Lab(
                id=5,
                name="已关闭实验室",
                location="志明楼999",
                capacity=10,
                open_time="09:00",
                close_time="17:00",
                status=0,
            ),
        ]
    )

    db.add_all(
        [
            Equipment(
                id=1,
                lab_id=4,
                name="RTX4090",
                spec="24G 显存",
                description="深度学习训练显卡",
                quantity=4,
                status=1,
            ),
            Equipment(
                id=2,
                lab_id=4,
                name="显卡",
                spec="RTX5090 24G",
                description="多模态情感识别训练",
                quantity=2,
                status=1,
            ),
            Equipment(
                id=3,
                lab_id=1,
                name="服务器",
                spec="Dell R750",
                description="虚拟化实验宿主",
                quantity=3,
                status=1,
            ),
            Equipment(
                id=4,
                lab_id=1,
                name="交换机",
                spec="48 口万兆",
                description="网络实验",
                quantity=2,
                status=1,
            ),
            Equipment(
                id=5,
                lab_id=2,
                name="电子显微镜",
                spec="SEM-2000",
                description="样品表面形貌观察",
                quantity=1,
                status=1,
            ),
            Equipment(
                id=6,
                lab_id=3,
                name="示波器",
                spec="4 通道 200MHz",
                description="信号测量",
                quantity=5,
                status=1,
            ),
            Equipment(
                id=7,
                lab_id=4,
                name="维修中的显卡",
                spec="RTX3080",
                description="故障待维修",
                quantity=1,
                status=0,
            ),
        ]
    )

    # 冲突样本的靶子：明天 09:00-11:00 计算机实验室已被通过审核的预约占用。
    # 用「明天」而不是固定日期，样本才不会因为日期过期而失效。
    tomorrow = (datetime.now() + timedelta(days=1)).date()
    db.add(
        Reservation(
            id=1,
            user_id=2,
            lab_id=1,
            equipment_id=None,
            date=tomorrow,
            start_time=time(9, 0),
            end_time=time(11, 0),
            remark="评估集种子预约",
            status=1,
        )
    )
