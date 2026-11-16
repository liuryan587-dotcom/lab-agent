# Lab Agent

一个面向实验室场景的智能预约系统。项目同时覆盖传统业务系统和 AI Agent：用户可以查询实验室、设备与开放规则，也可以通过自然语言生成预约申请；真正写入预约表前，系统会先生成待确认单，由用户点击确认后再提交。

这个项目适合作为 Python 后端、AI Agent 或全栈实习项目展示。它的重点不是简单调用一次大模型，而是把 RAG、工具调用、流式输出、会话记忆、权限控制和写操作安全放进一个可运行的业务闭环里。

## 项目亮点

- **完整业务闭环**：注册登录、JWT 鉴权、角色权限、实验室与设备管理、预约申请、管理员审核。
- **Agent 工具调用**：基于 LangGraph 编排 Agent，通过工具查询实验室、设备、开放时间和预约状态。
- **RAG 知识库**：使用 Markdown 规则文档构建 Chroma 向量库，结合本地 Ollama embedding 检索预约规则、安全规范和设备说明。
- **实时交互**：后端使用 SSE 流式返回 Agent 状态、工具调用过程和最终回答，前端实时展示执行步骤。
- **服务端多轮记忆**：按 `thread_id` 保存 user、assistant 和 tool 消息，追问时可以复用上一轮工具结果。
- **写操作安全边界**：Agent 只能生成 `pending_actions` 待确认单；用户确认后服务端重新校验，才写入 `reservations`。
- **可重复评估**：提供 30 条评估样本，覆盖 RAG、工具选择、写入行为、多轮记忆和安全性，并支持参数级断言。
- **数据库迁移**：使用 Alembic 管理 schema 版本，新环境运行迁移即可建表，模型变更可以通过版本脚本增量升级。

## 演示流程

```text
用户登录
  ↓
输入“人工智能实验室有哪些设备？”
  ↓
Agent 调用 list_lab_equipments
  ↓
SSE 流式显示工具执行过程和回答
  ↓
用户继续问“显卡那台的规格是什么？”
  ↓
服务端从同一个 thread_id 恢复历史，直接利用上一轮 ToolMessage
```

预约流程则是：

```text
用户用自然语言提出预约需求
  ↓
Agent 调用 create_lab_reservation
  ↓
服务端校验业务规则并生成待确认单
  ↓
用户点击“确认预约”
  ↓
服务端再次校验时间冲突、归属和过期状态
  ↓
写入 reservations，等待管理员审核
```

## 界面预览

**系统首页**：登录后展示开放实验室数量、与我相关的预约数和 AI 助手状态，并提供快捷入口。

<img src="assets/screenshots/home.png" alt="系统首页" width="880">

**AI 助手查设备**：用自然语言提问，Agent 调用 `search_equipments` 跨实验室检索，把结果整理成表格，并追问「设备 + 日期 + 时段」。

<img src="assets/screenshots/ai-chat-equipment-search.png" alt="AI 助手查询显卡" width="880">

**生成待确认预约**：参数齐全后 Agent 调用 `create_lab_reservation`，只生成一张 5 分钟内有效的待确认卡片；点击「确认预约」后服务端重新校验并落库，会话里会补一条「已确认并提交：预约号 #199」。

<img src="assets/screenshots/ai-chat-pending-action.png" alt="AI 助手生成待确认预约" width="880">

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 后端 | Python 3.13、FastAPI、SQLAlchemy、Pydantic Settings、Uvicorn |
| Agent | LangGraph、LangChain Core、OpenAI 兼容模型接口 |
| 检索 | Chroma、Ollama embedding |
| 数据库 | MySQL 8.x；评估脚本支持独立 SQLite |
| 认证 | JWT、bcrypt、角色权限控制 |
| 前端 | Vue 3、Vite、Vue Router、Element Plus、Axios |
| 流式通信 | Server-Sent Events（SSE） |

## 项目结构

```text
lab-agent/
├── backend/
│   ├── app/
│   │   ├── api/              HTTP 路由与 SSE 接口
│   │   ├── models/           SQLAlchemy 数据模型
│   │   ├── schemas/          Pydantic 请求/响应模型
│   │   ├── services/         业务逻辑、Agent、RAG、历史与 Trace
│   │   ├── dependencies/     登录用户依赖
│   │   └── utils/             JWT、密码等基础能力
│   ├── data/kb/              知识库 Markdown 文档
│   ├── tests/                 服务测试与 Agent 评估集
│   ├── pyproject.toml
│   └── README.md              后端详细启动说明
├── frontend/
│   ├── src/views/            登录、预约、管理和 AI 对话页面
│   ├── src/api/              后端 API 封装
│   └── package.json
├── assets/screenshots/       README 用的界面截图
├── docs/                     架构、评估和学习记录
└── README.md
```

## 本地运行

### 1. 准备依赖

需要准备：

- Python 3.13
- `uv`
- Node.js 22+
- MySQL 8.x
- Ollama
- 一个 OpenAI 兼容的大模型 API

### 2. 配置后端

```powershell
cd backend
Copy-Item .env.example .env
```

编辑 `backend/.env`，至少填写数据库、JWT 和模型配置：

```dotenv
DATABASE_URL=mysql+pymysql://user:password@127.0.0.1:3306/lab_agent
JWT_SECRET_KEY=replace-with-a-random-secret
LLM_API_KEY=your-api-key
LLM_BASE_URL=https://your-provider.example.com/v1
LLM_MODEL=your-model-name
```

如果暂时只想体验登录、实验室、设备和预约等传统业务，可以使用项目提供的 SQLite 演示库，不需要先安装 MySQL：

```powershell
cd backend
Copy-Item .env.example .env
# 把 .env 中的 DATABASE_URL 改成：
# DATABASE_URL=sqlite:///./data/demo.db
\.venv\Scripts\python.exe scripts\seed_demo.py --reset
```

演示账号：

| 账号 | 密码 | 角色 |
| --- | --- | --- |
| `demo_student` | `Demo123456!` | 学生 |
| `demo_admin` | `Demo123456!` | 管理员 |

SQLite 演示库只覆盖业务页面；AI 对话仍需要在 `.env` 中配置真实的 OpenAI 兼容模型，并启动 Ollama embedding 服务。

先创建空数据库：

```sql
CREATE DATABASE lab_agent DEFAULT CHARACTER SET utf8mb4;
```

安装依赖并准备 embedding 模型：

```powershell
uv sync
ollama pull qwen3-embedding:8b
```

新建空数据库首次启动前执行：

```powershell
uv run alembic upgrade head
```

早期已有数据库需先核对结构并标记基线，按 [已有数据库接入步骤](backend/README.md#已有数据库接入-alembic) 操作；SQLite Demo 种子脚本会自动执行迁移。

启动后端：

```powershell
uv run uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:8000>，看到 `{"message":"Hello FastAPI"}` 即表示服务已启动。

### 3. 启动前端

另开终端：

```powershell
cd frontend
Copy-Item .env.example .env.development
npm install
npm run dev
```

访问 <http://127.0.0.1:5173>。注册接口默认创建 `student` 用户；需要查看管理功能时，可以在数据库中手工提权：

```sql
UPDATE users SET role = 'admin' WHERE username = '你的账号';
```

完整的环境变量、常见报错和目录说明见 [backend/README.md](backend/README.md)。

## Agent 评估

评估集位于 [backend/tests/eval](backend/tests/eval)，不会污染业务数据库，而是每次使用独立的 SQLite 数据库和固定种子数据。

```powershell
cd backend

# 先跑 3 条确认链路
.\.venv\Scripts\python.exe tests\eval\runner.py --limit 3

# 全量评估
.\.venv\Scripts\python.exe tests\eval\runner.py --repeat 3

# 多轮记忆评估
.\.venv\Scripts\python.exe tests\eval\runner.py --multi-turn
```

评估覆盖：

| 类别 | 验证内容 |
| --- | --- |
| RAG | 文档检索命中和回答内容 |
| tool | 工具选择、调用集合和工具参数 |
| write | 预约生成、冲突检查和待确认单 |
| multi-turn | 会话记忆和指代消解 |
| safety | 提示词注入下业务表是否被越权写入 |

已有一轮记录结果：30 条样本 × 3 轮全部通过；工具选择准确率 100%，检索命中率 100%，系统写安全率 100%。详细口径、样本设计和限制见 [backend/tests/eval/README.md](backend/tests/eval/README.md)。

可直接查看 [Agent 评估 HTML 报告](docs/agent-eval-report.html)。该报告由 2026-10-27 的历史 JSON 生成；老结果没有保存工具参数和 Ollama 状态，因此相应字段会明确标为未记录。后续评估可用 `backend/scripts/render_eval_report.py` 从新 JSON 生成完整明细报告。

## 验证命令

前端生产构建：

```powershell
cd frontend
npm run build
```

后端待确认单服务测试：

```powershell
cd backend
.\.venv\Scripts\python.exe tests\test_pending_action.py
```

安装开发依赖后运行预约业务规则测试：

```powershell
cd backend
uv sync --dev
.\.venv\Scripts\python.exe -m pytest tests -q
```

这组测试覆盖待确认单的越权、过期、重复确认，以及预约时间范围、开放时间和时段冲突校验。

## 面试可以重点讲什么

1. **为什么预约不能由模型直接写数据库？**
   模型可能被用户提示词诱导跳过确认，因此 Agent 只创建待确认单；确认接口检查当前用户、状态、过期时间和预约冲突后才真正写库。

2. **为什么要保存 ToolMessage？**
   只保存文本会丢失上一轮工具结果。服务端保存完整消息后，第二轮追问可以直接使用已有结果，减少重复查询。

3. **如何验证 Agent 不是“看起来能用”？**
   用固定数据集断言工具集合、工具参数、文档命中、数据库增量和安全指标，改动前后可以重复对比。

## 当前限制与后续计划

- 早期已有数据库需要先核对 schema，再 `alembic stamp` 标记基线；新库直接执行迁移。
- 预约冲突检查已增加冲突查询索引和事务行锁；如果部署到高并发生产环境，仍建议进一步引入专门的时间段约束或预约写入队列。
- 历史消息目前按数量截断，长对话还没有摘要压缩。
- 前端自动化测试和确认接口的端到端评估仍可继续补充。
- 当前本地启动依赖 MySQL、Ollama 和模型 API，后续可以增加 SQLite/Mock 模式降低体验门槛。

这些限制是后续工程化改进方向，也可以作为面试中的技术取舍和迭代计划来讨论。

## License

本项目目前主要用于学习、作品展示和面试演示。
