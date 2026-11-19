# 后端镜像：uv 安装依赖 + 启动前跑迁移
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# uv 用来按 uv.lock 精确还原依赖，比 pip 快且可复现
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先只拷依赖描述，利用镜像分层缓存：改代码不会重装依赖
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000

# 启动前先迁移：容器重建后表结构也能跟上
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
