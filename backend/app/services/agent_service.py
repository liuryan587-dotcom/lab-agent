import json
import logging
import time
from datetime import datetime
from typing import Any
from uuid import uuid4

from langchain_openai import ChatOpenAI
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from app.common.exceptions import BusinessException
from app.config import settings
from app.database import SessionLocal
from app.models.user import User
from app.schemas.ai import ChatRequest
from app.services import agent_tools, chat_history_service, trace_service

# 注意：from fastapi import logger 拿到的是「模块」而不是 logger 实例，
# 调用 logger.exception() 会抛 AttributeError，反而把真实异常顶掉
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是智能实验室预约系统的 Agent，回答要简洁。

## 可用工具
1. search_lab_docs：查实验室规则、安全、开放时间等文档
2. list_open_labs：查当前开放的实验室
3. search_equipments：按设备名跨实验室搜索，回答「哪个实验室有 XX 设备」
4. list_lab_equipments：查某个实验室的设备（已经能确定是哪个实验室时用）
5. create_lab_reservation：生成待确认预约（参数齐了就直接调用）
6. find_lab_free_slots：查询可预约时段

## 工具参数约定
查询类工具（list_lab_equipments、search_equipments）可以直接传实验室名称，
不需要先查 ID，**也不要为了拿 ID 多调一次 list_open_labs**。
只有 create_lab_reservation 必须使用数字 ID：缺 ID 时先调 list_open_labs 查到再创建，不要瞎写。

## 必须遵守
今天是几号，看下面「当前时间」那一节，**不要调用 get_today 反复确认，也不要回答「我需要确定明天的具体日期」**。
用户说「明天」就是当前时间 +1 天，直接换算成具体日期再往下走。

参数（实验室、日期、时间、设备）齐了就直接调用 create_lab_reservation 生成待确认卡片。
真正的提交由用户点击卡片完成。

调用 create_lab_reservation 之后只是生成了一张**待确认卡片**，并没有真正提交。
必须告诉用户「请点击卡片上的『确认预约』」，**不要说「预约已成功」**。
工作流的确认环节里如果缺少了 equipment_id，请先 list_lab_equipments 查到了 equipment_id 再创建，不要瞎写。

用户问「某天还有哪些时间能约」「还有空位吗」「几点能约」时，
必须先调用 find_lab_free_slots，不要用 list_open_labs 或 search_lab_docs 猜。

预约成功后状态是待审核，必须管理员确认后实验室（或设备）才能使用。
不要瞎编数据库里没有的实验室或者设备信息。
如果是问开放时间或者实验室规则，优先调用 search_lab_docs，不要凭空回复。

## 工具返回约定
工具返回 JSON。看到 {"ok": false, "retryable": false} 时，说明重试没有意义：
不要重复调用同一个工具，按 hint 换个工具或直接告诉用户失败原因。
retryable 为 true 时，可以按 hint 调整参数后重试一次。
同一个工具连续失败两次，必须停下来向用户说明情况，不要继续尝试。
"""
# 工具英文名 -> 页面上给人看的中文过程文案
TOOL_LABELS = {
    "search_lab_docs": "检索实验室知识库",
    "list_open_labs": "查询开放实验室",
    "list_lab_equipments": "查询实验室设备",
    "search_equipments": "搜索实验设备",
    "create_lab_reservation": "生成待确认预约",
    "get_today": "获取今天日期",
    "find_lab_free_slots": "查询可预约时段",
}


WEEKDAYS = "一二三四五六日"


def _system_prompt() -> str:
    """每轮现拼系统提示，把「现在几点」写进去。

    日期是服务端已知的事实，不该让模型去调 get_today 查，更不该让它从历史消息里
    推断——会话恢复时，历史里的日期可能是几天前的，模型会把那天当成今天。
    """
    now = datetime.now()
    return (
        SYSTEM_PROMPT
        + "\n## 当前时间\n"
        + f"现在是 {now:%Y-%m-%d %H:%M}（星期{WEEKDAYS[now.weekday()]}）。\n"
        + "涉及日期、星期、是否已经过期的判断，一律以这里为准，\n"
        + "不要从历史消息或历史工具返回里推断今天是几号。\n"
        + "今天日期、可预约时段这类会随时间变化的信息，必须在本轮重新调用工具获取；\n"
        + "历史里的同类结果只能用来理解用户意图，不能当作事实。\n"
    )


def build_initial_messages(messages_in: list) -> dict:
    """构造图的初始输入。

    生产路径（stream_agent）和评估脚本都从这里拿输入，避免两边各拼一份。
    评估脚本曾经直接用 SYSTEM_PROMPT，绕过了「当前时间」注入，
    结果评估里测到的行为和线上不一致。
    """
    return {"messages": [SystemMessage(content=_system_prompt()), *messages_in]}


def _chunk_text(chunk: Any) -> str:
    """从模型流式 chunk 里抠出纯文本。

    content 有时是 str，有时是 [{type, text}, ...] 这种块列表，要统一成字符串。
    """
    if chunk is None:
        return ""
    # chunk 可能是 AIMessageChunk，真正字在 .content
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text") or "")
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return str(content) if content is not None else ""


def _tool_output_preview(output: Any, limit: int = 200) -> str:
    """把工具结果收成短预览，避免整段 JSON 刷到前端过程区。"""
    # LangGraph 里工具结果经常是 ToolMessage，正文在 .content
    if isinstance(output, ToolMessage):
        output = output.content
    text = output if isinstance(output, str) else str(output)
    # 太长就截断，末尾加省略号
    return text if len(text) <= limit else text[:limit] + "..."


def _pending_from_output(output: Any) -> dict | None:
    """工具结果是「待确认」时，把 action_id 抠出来给前端渲染卡片。

    注意不能用 preview：那是截断到 200 字符的，JSON 会被切坏。
    """
    if isinstance(output, ToolMessage):
        output = output.content
    text = output if isinstance(output, str) else str(output)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("status") != "pending_confirmation":
        return None
    return {"action_id": payload.get("action_id"), "summary": payload}


def _build_history(data: ChatRequest) -> list:
    """前端只传 user/assistant 文本，转成 LangChain 消息对象"""
    history = []
    for message in data.messages or []:
        if message.role == "user" and message.content.strip():
            history.append(HumanMessage(content=message.content.strip()))
        elif message.role == "assistant" and message.content.strip():
            history.append(AIMessage(content=message.content.strip()))
    if not history:
        raise BusinessException(code=400, message="请输入您要对话的内容")
    return history


def _last_user_text(messages: list) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return str(message.content or "").strip()
    return ""


def _last_request_text(data: ChatRequest) -> str:
    for message in reversed(data.messages or []):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""


def _looks_failed(output) -> bool:
    if isinstance(output, ToolMessage):
        output = output.content
    text = output if isinstance(output, str) else str(output)
    return text.lstrip().startswith('{"ok": false') or '"ok": false' in text[:40]


def _sum_tokens(messages) -> tuple[int, int]:
    prompt = completion = 0
    for message in messages or []:
        if not isinstance(message, AIMessage):
            continue
        usage = getattr(message, "usage_metadata", None) or {}
        prompt += usage.get("input_tokens") or 0
        completion += usage.get("output_tokens") or 0
    return prompt, completion


def _prepare_messages(thread_id: str, user_id: int, data: ChatRequest) -> list:
    """优先用服务端保存的会话历史；没有则退回客户端传来的纯文本。"""
    db = SessionLocal()
    try:
        history = chat_history_service.load_messages(db, thread_id, user_id)
    finally:
        db.close()

    if not history:
        return _build_history(data)

    text = _last_request_text(data)
    if not text:
        raise BusinessException(code=400, message="请输入您要对话的内容")
    return [*history, HumanMessage(content=text)]


def _persist_turn(
    *,
    thread_id: str,
    user_id: int,
    messages_in: list,
    final_messages: list | None,
    answer_text: str,
    question: str,
    status: str,
    latency_ms: int,
    tool_steps: list[dict],
    error_message: str,
) -> None:
    """把本轮的完整消息（含 tool）和 trace 落库。失败不影响已经流出去的回复。"""
    db = SessionLocal()
    try:
        # inputs = [system] + messages_in，messages_in 占下标 1..N，
        # 最后一条（本轮用户输入）在下标 N。所以从 N 开始切，既包含用户这句，
        # 也包含后面新产生的 assistant / tool 消息。
        new_messages = []
        if final_messages:
            new_messages = list(final_messages[len(messages_in) :])
        if not new_messages and answer_text and messages_in:
            # on_chain_end 没拿到时退化：至少把用户这句和回答存下来
            new_messages = [messages_in[-1], AIMessage(content=answer_text)]
        if new_messages:
            chat_history_service.append_messages(db, thread_id, user_id, new_messages)

        prompt_tokens, completion_tokens = _sum_tokens(final_messages)
        trace_service.record(
            db,
            thread_id=thread_id,
            user_id=user_id,
            question=question,
            model=settings.LLM_MODEL,
            status=status,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tool_steps=tool_steps,
            error_message=error_message,
        )
    except Exception:
        logger.exception("持久化对话或 trace 失败（不影响本次回复）")
    finally:
        db.close()


async def stream_agent(current_user: User, data: ChatRequest):
    """
    生成器：边跑 Agent 边 yield 事件，供 SSE 推给前端。
    事件类型：thread / status / tool_start / tool_end / pending_action / token / done / error
    """
    user_id = current_user.id
    thread_id = (data.thread_id or "").strip() or f"t{uuid4().hex[:12]}"

    started = time.perf_counter()
    messages_in: list = []
    final_messages = None
    answer_text = ""
    tool_steps: list[dict] = []
    tool_started_at: dict = {}
    status = "success"
    error_message = ""

    # 先把会话 id 告诉前端，之后每轮都带回来
    yield {"type": "thread", "thread_id": thread_id}

    try:
        messages_in = _prepare_messages(thread_id, user_id, data)
        question = _last_user_text(messages_in)

        agent = build_agent(current_user, thread_id)
        # 系统提示每轮现拼：里面带「当前时间」，避免模型用历史里的旧日期
        inputs = build_initial_messages(messages_in)

        # yield = 先交出这一条，函数暂停；前端收到后再继续往下跑
        yield {"type": "status", "message": "正在思考..."}

        # astream_events: 图每走一步（调工具、吐字）都会冒出一个内部事件
        # 注意：同步的 stream_events 只支持 version="v3"，
        # v1/v2 协议必须走异步的 astream_events
        async for event in agent.astream_events(
            inputs,
            version="v2",
            config={"recursion_limit": 10},  # agent⇄tools 来回上限，防空转
        ):
            kind = event.get("event")
            if kind == "on_tool_start":
                name = event.get("name") or ""
                tool_started_at[event.get("run_id")] = time.perf_counter()
                yield {
                    "type": "tool_start",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),  # 没有中文映射就退回英文名
                }
            elif kind == "on_tool_end":
                name = event.get("name") or ""
                output = (event.get("data") or {}).get("output")
                started_at = tool_started_at.pop(event.get("run_id"), None)
                tool_steps.append(
                    {
                        "name": name,
                        "input": (event.get("data") or {}).get("input"),
                        "output": _tool_output_preview(output, limit=1000),
                        "latency_ms": (
                            int((time.perf_counter() - started_at) * 1000)
                            if started_at
                            else 0
                        ),
                        "status": "error" if _looks_failed(output) else "ok",
                    }
                )
                yield {
                    "type": "tool_end",
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    # 只给预览；完整结果仍在图内部 message 里给模型用
                    "preview": _tool_output_preview(output),
                }
                # 预约工具现在只生成待确认单，额外推一条事件让前端渲染确认卡片
                if name == "create_lab_reservation":
                    pending = _pending_from_output(output)
                    if pending:
                        yield {"type": "pending_action", **pending}
            elif kind == "on_chat_model_stream":
                # 只收agent节点的字；其他内部节点的噪声丢掉
                meta = event.get("metadata") or {}
                if meta.get("langgraph_node") not in (None, "agent"):
                    continue
                text = _chunk_text((event.get("data") or {}).get("chunk"))
                if text:
                    answer_text += text
                    yield {"type": "token", "content": text}
            elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                # 图的最终 state：里面是完整的 messages（含 tool_calls / ToolMessage）
                output = (event.get("data") or {}).get("output")
                if isinstance(output, dict) and output.get("messages"):
                    final_messages = output["messages"]

        # 正常跑完：不要在 done 里再带一份全文，前端已经用 token 拼好了
        yield {"type": "done"}
    except BusinessException as exc:
        # 流已经是SSE，错误也要用 yield，别raise 成普通JSON
        # 使用 getattr 安全获取，防止 AttributeError 导致生成器崩溃
        status = "error"
        error_message = getattr(exc, "message", str(exc))
        logger.exception("Agent 业务异常")  # 打印真实堆栈，方便排查
        yield {"type": "error", "message": error_message}
    except Exception:
        # 别把真实原因吞掉：不打印堆栈的话，前端只看到一句笼统提示，无法排查
        status = "error"
        error_message = "大模型调用失败，请稍后重试"
        logger.exception("Agent 流式执行异常")  # 打印真实堆栈，方便排查
        yield {"type": "error", "message": error_message}
    finally:
        _persist_turn(
            thread_id=thread_id,
            user_id=user_id,
            messages_in=messages_in,
            final_messages=final_messages,
            answer_text=answer_text,
            question=_last_user_text(messages_in),
            status=status,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tool_steps=tool_steps,
            error_message=error_message,
        )


def build_agent(current_user: User, thread_id: str | None = None):
    tools = agent_tools.build_tools(current_user, thread_id)
    llm = ChatOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
        model=settings.LLM_MODEL,
        temperature=0,
    ).bind_tools(
        tools,
        # 方案 C：禁止模型一轮返回多个 tool_call。
        # 双保险——方案 A 已经让工具各自持有 Session，但关掉并行还能避免
        # 一次对话瞬间占用 N 个数据库连接（连接池只有 5+10）
        parallel_tool_calls=False,
    )

    def agent_node(state: MessagesState):
        """langGraph 执行的工作流的节点"""
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)  # 调用大模型的节点
    graph.add_node("tools", ToolNode(tools))  # tool call的节点
    graph.add_edge(START, "agent")  # 流程的起点，call LLM
    graph.add_conditional_edges(
        "agent", tools_condition
    )  # 看有无tool_call 有就继续call 没有就END输出
    graph.add_edge("tools", "agent")  # 让agent看tool调用的结果

    return graph.compile()
