# 智能实验室预约系统 · 后端

FastAPI + SQLAlchemy + LangGraph 的实验室预约系统。管理员维护实验室与设备，学生预约，AI 助手可以对话查询并用工具直接完成预约。

---

## 1. 这个后端由什么组成

| 依赖 | 版本要求 | 用来做什么 |
|---|---|---|
| Python | 3.13 | 运行环境 |
| uv | 最新 | 依赖管理与虚拟环境（项目用 `uv.lock` 锁定版本） |
| MySQL | 8.x | 存业务数据（用户、实验室、设备、预约） |
| Ollama | 最新 | 提供知识库的 **embedding 模型**（`kb_service.py` 会连本机 11434 端口） |
| 大模型 API | 任意兼容 OpenAI 协议的 | 供 AI 助手对话与工具调用 |

> ⚠️ **最容易被忽略的一点：即使你的大模型用的是云端 API，Ollama 仍然是必需的。**
> 因为知识库检索用的向量化模型跑在本地 Ollama 上，见 `app/services/kb_service.py` 的 `get_embedding_fn()`。

---

## 2. 跑起来（按顺序执行）

### 第 1 步：写配置文件

```powershell
cd backend
Copy-Item .env.example .env
```

然后打开 `.env`，把这几项改成你自己的：

- `DATABASE_URL` — 你的 MySQL 用户名和密码
- `JWT_SECRET_KEY` — 用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成一串
- `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` — 你的大模型服务信息

> 这三项 LLM 配置是**必填**的。`app/config.py` 里的 `Settings` 会在启动时校验，缺一项就直接启动失败。

### 第 2 步：建数据库

只需要建**空库**，表结构通过 Alembic 迁移创建：

```sql
CREATE DATABASE lab_agent DEFAULT CHARACTER SET utf8mb4;
```

### 第 3 步：装依赖

```powershell
uv sync
```

依赖安装完成后，为**新建空库**执行迁移（仍在 `backend/` 目录）：

```powershell
uv run alembic upgrade head
```

已有业务数据库请先阅读文末接入步骤，不要直接运行初始迁移。

### 第 4 步：拉 embedding 模型

```powershell
ollama pull qwen3-embedding:8b
```

> 模型名必须和 `app/services/kb_service.py` 里的 `model_name` 一致。想换别的模型，改那里。

### 第 5 步：确认知识库文档在

```powershell
ls data/kb
```

应该看到 4 个 `.md` 文件（安全规范、开放时间、设备使用、预约规则）。**第一次启动时**程序会把这几个文件写进向量库，落在 `data/chroma/`。

### 第 6 步：启动

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

看到类似这样的输出就成功了：

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

验证一下：浏览器打开 <http://127.0.0.1:8000>，应该返回 `{"message": "Hello FastAPI"}`。

### 第 7 步：开一个管理员账号

注册接口创建的用户 `role` 固定是 `student`（见 `app/services/auth_service.py` 的 `register`），所以**管理员的审核、实验室管理这些功能看不到**。需要手工提权：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的账号';
```

---

## 3. 前端怎么跑

前端是独立目录，另开一个终端：

```powershell
cd ../frontend
npm install
npm run dev
```

它默认请求 `http://127.0.0.1:8000`（配置在 `frontend/.env.development`）。前端起在 5173 端口，后端 CORS 白名单里也只放行了 5173，改端口要两边一起改。

---

## 4. 目录说明：只需要看这两个目录

```
backend/
├── app/              ← 真正的代码都在这里（约 40 个文件）
│   ├── main.py           程序入口：建 app、注册路由、注册异常处理器
│   ├── config.py         读 .env 配置
│   ├── database.py       数据库连接、Session 工厂、Base 基类
│   ├── api/              HTTP 层：收参数、调 service、返回
│   ├── schemas/          数据形状与校验（Pydantic）
│   ├── services/         业务规则 ← 项目最核心的部分
│   ├── models/           数据库表结构（SQLAlchemy ORM）
│   ├── utils/            密码哈希、JWT
│   ├── common/           统一响应体、异常定义、日志
│   └── dependencies/     依赖注入（登录鉴权）
├── data/kb/          知识库源文件（Markdown）
├── data/chroma/      向量库落盘（自动生成，不用管）
└── .venv/            ← 第三方库，一万多个文件，绝对不要进去看
```

**看代码时请把 `.venv/` 从搜索范围里排除**，否则会被淹没，误以为项目很大。

---

## 5. 一次请求是怎么走完的

以「登录」为例，这也是理解整个项目最好的入口：

```
浏览器点「登录」
   │  POST http://127.0.0.1:8000/api/auth/login
   │  body: {"username": "...", "password": "..."}
   ▼
frontend/src/views/Login.vue      表单校验 → 调 loginApi
   ▼
frontend/src/utils/request.js     axios 拦截器：自动带上 Authorization 头
   ▼
app/api/__init__.py               把 /api 和各个子路由拼起来
   ▼
app/api/auth.py                   login()：只管收发，不写业务
   ▼
app/schemas/auth.py               LoginRequest 校验请求体格式
   ▼
app/database.py                   Depends(get_db) 提供数据库 Session
   ▼
app/services/auth_service.py      业务：查用户、比对密码、发 token
   ├── app/utils/password.py        bcrypt 校验密码
   ├── app/models/user.py           生成 SELECT 语句
   └── app/utils/jwt.py             签发 JWT
   ▼
app/common/response.py            包成 {code, message, data}
   ▼
前端存进 localStorage，跳转首页
```

**建议**：不要只看这段文字。按 `../docs/login-flow-walkthrough.md` 里的步骤，自己在每一层打断点看真实数据，那才是真的懂了。

---

## 6. 常见问题

| 现象 | 原因 | 怎么修 |
|---|---|---|
| 启动报 `ValidationError: LLM_API_KEY field required` | `.env` 里少了必填项 | 对照 `.env.example` 补齐三项 LLM 配置 |
| 启动报 `Access denied for user` | MySQL 账号密码不对 | 检查 `DATABASE_URL` |
| 启动报 `Unknown database 'lab_agent'` | 库还没建 | 执行第 2 步的建库 SQL |
| 知识库检索报连接错误 / 一直连不上 | Ollama 没启动或模型没拉 | `ollama list` 确认模型在，`ollama serve` 确认服务在 |
| 第一次对话特别慢 | 正在加载 embedding 模型 | 正常，只有第一次慢 |
| AI 对话报「大模型调用失败」 | API Key 或 base_url 不对 | 检查 `LLM_BASE_URL` 结尾是否带 `/v1` |
| 登录后看不到审核菜单 | 账号还是 student | 执行第 7 步的提权 SQL |

---

## 7. 已知待改进（学习时可以先跳过）

按重要性排列，都是有意留着的现状：

- **新数据库通过 Alembic 迁移创建表结构**。已有数据库首次接入时需先核对 schema 并标记基线，不能直接执行初始迁移。
- **预约冲突检查不是原子的**（先查再插），并发下可能重复预约
- **对话历史按条数硬截断**（`MAX_HISTORY_MESSAGES = 40`），没有做摘要压缩，长对话会丢早期上下文
- **前端没有自动化测试**，交互靠手工验证

---

## 8. 测试

| 命令（在 backend 目录下执行） | 覆盖什么 | 需要什么 |
|---|---|---|
| `.\.venv\Scripts\python.exe tests\test_pending_action.py` | 待确认单的安全边界：越权确认/取消、过期、重复确认 | 无（SQLite，秒级） |
| `.\.venv\Scripts\python.exe tests\eval\runner.py --repeat 3` | 32 条 Agent 评估集，产出各项指标 | Ollama + 大模型配置 |
| `.\.venv\Scripts\python.exe tests\eval\runner.py --multi-turn` | 6 条多轮记忆样本 | 同上 |

**必须用项目 `.venv` 的解释器**，不要用系统/Anaconda 的 `python`——
依赖只装在虚拟环境里，用错解释器会从别的 site-packages 导入，报莫名其妙的错。
评估集 runner 会自己检查这一点。

评估集的设计、指标口径和历次结果见 [`tests/eval/README.md`](tests/eval/README.md)。

## 已有数据库接入 Alembic

项目早期版本在应用启动时用 `Base.metadata.create_all()` 建表。要把这种已有数据库纳入迁移管理：

1. 先备份数据库。
2. 确认现有表、列、外键和索引与 `migrations/versions/5ce161a3c16f_baseline_schema.py` 一致。预约冲突索引允许尚未创建，下一条迁移会补齐；如果已有同名索引，需确认列及顺序正确。其他差异需要先单独修复。`stamp` 只记录迁移版本，不会创建或修复表。
3. 确认一致后，在 `backend/` 目录运行：

   ```powershell
   uv run alembic stamp 5ce161a3c16f
   uv run alembic upgrade head
   uv run alembic check
   uv run alembic current
   ```

新建空数据库不要执行 `stamp`，直接 `uv run alembic upgrade head`。

迁移连接地址来自 `.env` 或环境变量 `DATABASE_URL`，与应用配置一致；`alembic.ini` 不存数据库密码。当前没有对本地 MySQL 业务库自动执行迁移或 stamp。

## 后续修改表结构

修改 SQLAlchemy 模型后，在已升级到最新版本的开发数据库上执行：

```powershell
uv run alembic revision --autogenerate -m "describe schema change"
# 审查生成的 upgrade / downgrade，再执行：
uv run alembic upgrade head
uv run alembic check
```

自动生成不保证识别字段重命名等语义，迁移脚本必须人工审查。将迁移文件与模型修改一起提交。`uv run alembic downgrade -1` 会执行上一版本的回退逻辑，可能删除字段或数据，只在备份后的可回退场景使用。
