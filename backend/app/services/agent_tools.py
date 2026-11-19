from contextlib import contextmanager
from datetime import datetime

import json
import logging

from langchain_core.tools import tool

from app.common.exceptions import BusinessException
from app.database import SessionLocal
from app.models.lab import Lab
from app.models.user import User
from app.schemas.reservation import ReservationCreateRequest
from app.services import (
    equipment_service,
    kb_service,
    lab_service,
    pending_action_service,
    reservation_service,
)

logger = logging.getLogger(__name__)


@contextmanager
def _tool_session():
    """每个工具调用一个独立 Session。

    LangGraph 的 ToolNode 会用线程池并发执行同一轮的多个 tool_call。
    如果所有工具共享 Depends(get_db) 传来的那一个 Session，同一个 pymysql
    连接就会被多线程交错读写，表现为 "Packet sequence number wrong" /
    "'NoneType' object has no attribute 'read'"，随后 Session 进入
    invalid transaction，把整个请求后续的查询全部毒死。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()  # close 会隐式 rollback，避免 invalid transaction 扩散


def _err(message: str, *, retryable: bool = False, hint: str | None = None) -> str:
    """工具统一的错误返回。

    retryable 是给模型看的信号：
      False —— 重试没用，别重复调同一个工具，换方案或直接告诉用户
      True  —— 参数可以改，最多重试一次
    """
    payload: dict[str, object] = {
        "ok": False,
        "retryable": retryable,
        "error": message,
    }
    if hint:
        payload["hint"] = hint
    return json.dumps(payload, ensure_ascii=False)


def _resolve_lab_id(db, raw: str | int) -> tuple[int | None, str | None]:
    """把模型传来的 lab_id 解析成数据库里的真实 id。

    模型经常把实验室名称塞进 lab_id。如果直接在函数签名上写 int，
    Pydantic 会在进入函数体之前就抛 ValidationError，工具里的 except
    根本捕不到，模型只能看到一段英文报错然后盲目重试。
    所以这里自己收、自己解析，把失败变成结构化提示。

    返回 (lab_id, 错误提示)，成功时错误提示为 None。
    """
    text = str(raw).strip()

    if text.isdigit():
        lab = db.get(Lab, int(text))
        if lab:
            return lab.id, None
        return None, f"实验室 id={text} 不存在，请先用 list_open_labs 确认可选的 id"

    labs = db.query(Lab).filter(Lab.name.ilike(f"%{text}%")).limit(5).all()
    if len(labs) == 1:
        return labs[0].id, None
    if labs:
        options = "、".join(f"{lab.id}={lab.name}" for lab in labs)
        return None, f"「{text}」匹配到多个实验室（{options}），请改用其中一个的数字 id"
    return (
        None,
        f"没有找到名称包含「{text}」的实验室，请先调用 list_open_labs 查看可选项",
    )


def build_tools(current_user: User, thread_id: str | None = None):
    # 立即取出 id：工具会在别的线程、别的 Session 里执行，
    # 而请求级 Session 可能在流式响应结束前就被关闭，ORM 实例会变成 detached
    user_id = current_user.id

    @tool
    def search_lab_docs(query: str) -> str:
        """根据用户的提问检索知识库"""
        try:
            return kb_service.search(query) or "没有检索到相关的资料"
        except Exception as exc:
            logger.exception("search_lab_docs 失败")
            return _err(
                str(exc),
                hint="知识库检索失败，请直接告诉用户暂时查不到文档，不要重复调用",
            )

    @tool
    def list_open_labs(keywords: str = "") -> str:
        """查询开放的实验室列表"""
        try:
            keywords = keywords.strip() or None
            with _tool_session() as db:
                page = lab_service.get_lab_page_list(
                    db, page=1, page_size=10, keywords=keywords, status=1
                )
                rows = [
                    {
                        "id": item.id,
                        "name": item.name,
                        "location": item.location,
                        "capacity": item.capacity,
                        "open_time": item.open_time,
                        "close_time": item.close_time,
                    }
                    for item in page.list
                ]
                total = page.total
            return json.dumps({"total": total, "labs": rows}, ensure_ascii=False)
        except Exception as exc:
            logger.exception("list_open_labs 失败")
            return _err(
                str(exc), hint="实验室列表查询失败，请告诉用户稍后再试，不要重复调用"
            )

    @tool
    def list_lab_equipments(lab_id: str | int, keywords: str = "") -> str:
        """查询某个实验室的设备列表。

        lab_id 传数字 id（如 2）或实验室名称（如 人工智能实验室）都可以。
        如果用户问的是「哪个实验室有某设备」，请改用 search_equipments。
        """
        try:
            keywords = keywords.strip() or None
            with _tool_session() as db:
                resolved, hint = _resolve_lab_id(db, lab_id)
                if resolved is None:
                    # 解析失败的提示已经带上了「下一步该怎么做」，这里不再补 hint
                    return _err(hint or "无法解析实验室")
                page = equipment_service.get_equipment_page_list(
                    db, page=1, page_size=10, keywords=keywords, lab_id=resolved
                )
                rows = [
                    {
                        "id": item.id,
                        "name": item.name,
                        "spec": item.spec,
                        "lab_id": item.lab_id,
                        "lab_name": item.lab_name,
                        "quantity": item.quantity,
                        "status": item.status,
                    }
                    for item in page.list
                ]
                total = page.total
            return json.dumps(
                {"total": total, "lab_id": resolved, "equipments": rows},
                ensure_ascii=False,
            )
        except Exception as exc:
            logger.exception("list_lab_equipments 失败 lab_id=%s", lab_id)
            return _err(str(exc), hint="设备列表查询失败，请告诉用户稍后再试")

    @tool
    def create_lab_reservation(
        lab_id: int,
        date: str,
        start_time: str,
        end_time: str,
        equipment_id: int | None = None,
        remark: str | None = None,
    ) -> str:
        """为一次预约生成「待确认单」。

        这个工具**不会直接写预约表**，只生成一条待用户确认的记录。
        调用后必须告诉用户：去界面上点击确认，预约才会真正提交。
        """
        try:
            # 这里要传 pydantic 的请求对象，而不是 ORM 模型：
            # ORM 模型的 date/start_time/end_time 现在是 DATE/TIME 类型，
            # 直接塞原始字符串会埋下类型不一致的隐患
            data = ReservationCreateRequest(
                lab_id=lab_id,
                equipment_id=equipment_id,
                date=date,
                start_time=start_time,
                end_time=end_time,
                remark=remark,
            )
            with _tool_session() as db:
                # current_user 可能是 detached 实例，重新挂到当前 Session 上再用
                user = db.get(User, user_id)
                if user is None:
                    return _err("当前用户不存在", hint="请提示用户重新登录后再试")
                # 生成待确认单之前先跑一遍业务校验，避免让用户确认一个注定失败的预约。
                # 用户点确认时还会再跑一遍（TOCTOU），这里只是提前暴露问题。
                reservation_service.validate_reservation(db, data)
                action = pending_action_service.create_pending(
                    db,
                    user_id,
                    "create_lab_reservation",
                    data.model_dump(),
                    thread_id=thread_id,
                )
                action_id = action.id
            return json.dumps(
                {
                    "ok": True,
                    "status": "pending_confirmation",
                    "action_id": action_id,
                    "message": "已生成待确认预约，需要用户在界面上点击确认才会真正提交",
                    "expire_in_seconds": pending_action_service.PENDING_TTL_SECONDS,
                    "lab_id": lab_id,
                    "equipment_id": equipment_id,
                    "date": date,
                    "start_time": start_time,
                    "end_time": end_time,
                },
                ensure_ascii=False,
            )
        except BusinessException as exc:
            # 业务校验类错误（时段冲突、实验室已关闭等）：改参数有可能成功，允许重试一次
            return _err(
                exc.message,
                retryable=True,
                hint="按错误信息调整参数后最多重试一次；仍失败就把原因告诉用户",
            )
        except Exception as exc:
            logger.exception("create_lab_reservation 失败")
            return _err(str(exc), hint="预约提交失败，请告诉用户稍后再试，不要重复提交")

    @tool
    def search_equipments(keyword: str) -> str:
        """按设备名称/型号/说明跨所有实验室搜索设备，返回所属实验室和当前可用数量。

        当用户问「哪个实验室有 XX 设备」「哪些实验室有显卡」时用这个工具，
        不要逐个实验室调用 list_lab_equipments（那会一次发出 N 个并发查询）。
        keyword 传具体硬件名或功能词，如：显卡、服务器、交换机、示波器、相机。
        """
        try:
            # search_equipment 已经返回 JSON 字符串，这里不要再 dumps 一次
            with _tool_session() as db:
                return equipment_service.search_equipment(db, keyword)
        except Exception as exc:
            logger.exception("search_equipments 失败 keyword=%s", keyword)
            return _err(str(exc), hint="设备搜索失败，请告诉用户稍后再试")

    @tool
    def find_lab_free_slots(lab_id: str | int, date: str, duration: int = 60) -> str:
        """查询某个实验室某天还能开始预约的时刻。

        date 必须是 YYYY-MM-DD。用户说「今天/明天/后天」时，先调用 get_today 拿到真实日期再传，
        不要把「明天」这两个字直接传进来。
        lab_id 可以传数字 id（如 2）或实验室名称（如 人工智能实验室）。
        本工具只查询，不会创建预约；用户选定某个时刻后，再调用 create_lab_reservation。
        返回里 slots 是分钟数，labels 是给用户看的 HH:MM。
        """
        try:
            day = datetime.strptime(date.strip(), "%Y-%m-%d").date()
        except ValueError:
            return _err(
                f"日期格式不对：{date}",
                retryable=False,
                hint="请按 YYYY-MM-DD 传，例如 2026-11-19；用户说“明天”时先调用 get_today",
            )
        try:
            with _tool_session() as db:
                resolved, hint = _resolve_lab_id(db, lab_id)
                if resolved is None:
                    return _err(hint or f"无法解析实验室 {lab_id}")
                return reservation_service.get_lab_free_starts(
                    db, resolved, day, duration
                )
            slots = data["slots"]
            labels = data["labels"]
            if not slots:
                return json.dumps(
                    {
                        "ok": True,
                        "count": 0,
                        "lab_id": resolved,
                        "date": day.isoformat(),
                        "duration": duration,
                        "hint": "该实验室当天已无可约时段，可以建议用户换一天或换一个实验室",
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "ok": True,
                    "count": len(slots),
                    "lab_id": resolved,
                    "date": day.isoformat(),
                    "duration": duration,
                    "slots": slots[:20],
                    "labels": labels[:20],
                    "truncated": len(slots) > 20,
                },
                ensure_ascii=False,
            )
        except BusinessException as exc:
            # 实验室不存在、容量未设置这类：改参数有可能成功，允许重试一次
            return _err(
                exc.message,
                retryable=True,
                hint="按错误信息修正参数后最多重试一次；仍失败就把原因告诉用户",
            )

        except Exception as exc:
            logger.exception("find_lab_free_slots 失败 lab_id=%s date=%s", lab_id, date)
            return _err(str(exc), hint="查询失败，请告诉用户稍后再试，不要重复调用")

    return [
        search_lab_docs,
        list_open_labs,
        list_lab_equipments,
        search_equipments,  # 必须注册，否则 bind_tools 绑不到，模型看不到这个工具
        create_lab_reservation,
        find_lab_free_slots,
    ]
