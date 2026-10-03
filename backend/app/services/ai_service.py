from httpx2 import query
from openai import OpenAI
from app.common.exceptions import BusinessException
from app.config import settings
from app.schemas.ai import ChatMessage, ChatRequest
import logging
from app.services import kb_service

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是实验室智能助手。你必须严格根据下面提供的【知识库内容】回答用户问题。

规则：
1. 只使用【知识库内容】里的信息作答，不要编造。
2. 知识库按实验室分别列出开放时间，例如"计算机实验室""化学实验室""物理实验室"。
   当用户笼统地问"实验室几点开门/开放时间"时，应把知识库中所有实验室的开放时间都列出来，而不是只找一个叫"实验室"的条目。
3. 如果知识库里确实没有相关信息，再回答"查不到"，并引导用户查看【实验室列表】或联系管理员。
"""


def get_client() -> OpenAI:
    """创建OpenAI的客户端"""
    if not settings.LLM_API_KEY:
        raise BusinessException(code=400, message="为获取到大模型的API_KEY")
    return OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)


def chat(data: ChatRequest):
    """大模型对话"""
    if not data.messages:
        raise BusinessException(code=400, message="对话内容为空")
    history = []
    for message in data.messages:
        if message.role in ("user", "assistant") and message.content.strip():
            history.append(message.model_dump())
    if not history:
        raise BusinessException(code=400, message="请输入您要对话的内容")

    # 取出用户的最新问题，进行知识库检索
    question = next(
        (item["content"] for item in reversed(history) if item["role"] == "user")
    )
    knowledge = kb_service.search(query=question)
    print(f"知识库检索结果: {knowledge}")
    system_prompt = SYSTEM_PROMPT
    if knowledge:
        system_prompt += f"\n\n实验室资料:\n{knowledge}"

    client = get_client()

    try:
        res = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                ChatMessage(role="system", content=system_prompt).model_dump(),
                *history,
            ],
        )
        content = res.choices[0].message.content
        if not content.strip():
            raise BusinessException(code=400, message="大模型没有返回内容")
        return content
    except Exception as e:
        logger.exception("大模型调用失败，真实错误信息: %s", str(e))
        raise BusinessException(code=400, message="大模型调用失败，请稍后重试")
