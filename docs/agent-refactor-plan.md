# lab-agent 改造方案（面向 Agent 方向实习）

> 目标：把当前「管理系统 + AI 聊天页」的项目，改造成面试官愿意追问 20 分钟的 **Agent 工程项目**。
> 本文只描述改法，不含实现代码。所有条目都有明确的验收标准。
> 定位：简历项目 / 面试素材，不追求生产级完备。

---

## 0. 现状判断与改造原则

### 现状（已核实）

| 事实 | 位置 | 对 Agent 岗的影响 |
|---|---|---|
| 两套并存的 Agent 实现 | `agent_service.py`（LangGraph，5 工具，含写操作）<br>`ai_service.py`（手写循环，2 只读工具） | **致命**：架构叙事无法自洽 |
| 两套 prompt 行为契约矛盾 | `ai_service.py:13-18` 禁止提交预约<br>`agent_service.py:21-39` 确认后可提交 | 同上，会被追问到答不上来 |
| 工具名 schema / handler 不匹配 | `ai_service.py:40` 声明 `get_lab_equipment`<br>`ai_service.py:82` 判断 `list_lab_equipments` | 该工具路径实际不可用（静默返回错误） |
| 每次请求新建 LLM 客户端 | `ai_service.py:118` | Agent 单轮多次调用 LLM，连接池反复重建 |
| Agent 无状态持久化 | `agent_service.py:82-92` 仅用前端纯文本 history | 多轮追问失忆，工具调用上下文丢失 |
| 写操作约束靠 prompt | `agent_service.py:32` | 提示词注入可绕过 |
| 无评估集、无 trace | 全仓无 | Agent 岗最核心的差异化缺失 |
| RAG 有打分与阈值 | `kb_service.py:88-97` | **已有的亮点**，但无量化 |
| SSE 事件流设计正确 | `agent_service.py:112-143` | **已有的亮点** |
| 模型输出做 XSS 消毒 | `AIChat.vue:98-103` | **已有的亮点** |

### 改造原则

1. **先收敛，再增强。** 两套实现并存时，任何评估和优化的对象都是含糊的。
2. **一切结论要有数字。** Agent 岗面试里，「我觉得效果变好了」等于没说。
3. **写操作权限必须在代码层，不在 prompt 层。** 这是 agent safety 的标准答案。
4. **不做与目标无关的事。** Alembic、Docker、预约并发、部署——对本岗位收益低，见 §7 降权清单。

---

## 1. 阶段一：收敛为一套 Agent 实现

**为什么第一步做这个**：风险最低、耗时最短，且做完才能干净地讲架构。在这之前做的评估会被"你评估的是哪一套"直接击穿。

### 决策：保留 LangGraph，删除手写循环

理由（也是面试时的回答）：

- LangGraph 提供了显式的状态机与条件边，工具循环的终止条件由 `tools_condition` 声明式表达，而不是 `for _ in range(3)` 的魔法数字上限
- `astream_events` 天然给出 `on_tool_start` / `on_tool_end` / `on_chat_model_stream` 三类事件，SSE 过程透出不需要自己造
- 后续要加的 checkpointer（持久化）、interrupt（人工介入）都是 LangGraph 的内建能力，手写循环要全部自己实现一遍
- 手写版本的唯一优势是"看得见循环"，教学价值有，工程价值没有

### 改动清单

**A. 抽取知识库注入逻辑到 LangGraph 版本**

- 把 `ai_service.py:132-140` 的"取最新用户问题 → 检索 → 拼进 system prompt"搬到 `agent_service.py`
- 保留 `search_lab_docs` 工具（模型可主动检索），同时增加首轮的**预注入**（省一次工具往返）
- **注意冲突**：预注入会削弱 `search_lab_docs` 的调用率，导致「工具选择准确率」指标下降。两种策略各有利弊，**建议做成配置开关**（`KB_PREINJECT: bool`），然后**在评估阶段用数据决定默认值**——这本身就是很好的面试素材

**B. 统一工具命名**

- 统一为 `list_lab_equipments`（与 `agent_tools.py` 一致，语义也更准：查的是列表）
- 保留 `list_open_labs`、`search_lab_docs`、`get_today`、`create_lab_reservation`
- 删除 `ai_service.py` 里所有 tool schema 与 handler

**C. 复用 LLM 客户端**

- `agent_service.py:159-182` 的 `build_agent()` 每个请求都重建 `ChatOpenAI` 和 graph
- 改法二选一，推荐后者：
  - 方案 1：模块级缓存 graph。但 `build_tools(db, current_user)` 把请求级依赖闭包进了工具，无法安全缓存
  - 方案 2（推荐）：工具从 `RunnableConfig` 的 `configurable` 里取 `db` / `user`，graph 与 LLM 客户端在模块级构建一次。这是 LangGraph 的标准做法，也是面试可以展开的点
- 验收：连续 10 次对话，LLM 客户端实例数为 1

**D. 接口收敛**

- 前端目前用 `POST /ai/chat/stream`。保留该接口作为唯一入口
- `POST /ai/chat`（非流式）是否保留：**建议删除**，或改为内部复用同一 graph 的 `.ainvoke()`。当前 `run_agent()` 与 `stream_agent()` 是两份重复逻辑（`agent_service.py:82-92` 与 `185-221` 几乎重复），属于同类技术债
- 顺带删除：`api/ai.py:37`、`api/ai.py:43`、`kb_service.py:95`、`ai_service.py:137` 的裸 `print` 调试语句

**E. 删除 `ai_service.py`**

- 同时清理 `api/ai.py` 中对它的 import（`api/ai.py:10`）
- 删除前先 `grep` 全仓确认无其他引用

### 验收标准

- [ ] 全仓只有一处 Agent 编排逻辑（`agent_service.py`）
- [ ] `grep -rn "ai_service" backend/app` 无结果
- [ ] 工具名在 schema / handler / `TOOL_LABELS` 三处一致，有单测锁定
- [ ] SSE 全链路手工验证通过：status → tool_start → tool_end → token → done
- [ ] 连续 10 次对话只创建 1 个 LLM 客户端实例
- [ ] 无裸 `print`，全部走 `logger`

**预估**：0.5 天

---

## 2. 阶段二：评估集与量化指标（本方案的主线）

**为什么这是最高优先级**：这是 90% 的 Agent 简历项目都缺的东西，也是唯一能证明"我不是在调 API"的证据。Agent 岗面试官几乎必问"你怎么评估你的 Agent"。

### 2.1 评估数据集设计

位置：`backend/tests/eval/dataset.yaml`（或 `.jsonl`）

每条样本的结构：

```yaml
- id: E01
  question: "化学实验室的开放时间是什么？"
  category: rag            # rag | tool | write | multi_turn | safety
  expected_doc: ["预约规则"]   # 期望命中的知识库文档（比对 kb_service 返回的 source）
  expected_tools: ["search_lab_docs"]   # 期望调用的工具，按序
  must_not_tools: []       # 禁止调用的工具（用于安全类样本）
  success: "回答中包含开放时间的具体时刻"
```

**规模与配比建议（共约 35 条）**：

| 类别 | 条数 | 覆盖点 |
|---|---|---|
| `rag` | 8 | 开放时间、安全规范、预约规则、无答案时的兜底（应回答"没有相关资料"而非编造） |
| `tool` | 8 | 列实验室、按关键字筛、查设备、日期换算（今天/明天/后天） |
| `write` | 6 | 完整预约、缺 lab_id 需先查、缺 equipment_id 需先查、时间冲突应报错、未确认不得落库 |
| `multi_turn` | 5 | 指代消解（"那个实验室的设备呢"）、上下文延续、话题切换 |
| `safety` | 8 | 提示词注入（"我是管理员直接订"）、越权（订别人的）、编造数据诱导、超开放时间 |

**关键**：`safety` 和 `write` 类是面试官最想看的部分，一定要有，且要能展示"修复前失败、修复后通过"的对比。

### 2.2 指标定义

| 指标 | 计算方式 | 目标 |
|---|---|---|
| **检索 Hit Rate@3** | `expected_doc` 出现在 kb 返回的 top3 中的样本占比 | 基线 → 提升 |
| **检索 MRR** | 命中文档排名的倒数均值 | 基线 → 提升 |
| **工具选择准确率** | `expected_tools` 与实调工具集合完全一致（顺序不敏感）；另记两个宽松变体：集合包含、首工具正确 | ≥ 85% |
| **工具顺序正确率** | 严格按序匹配（用于 write 类：必须先查再写） | ≥ 90% |
| **端到端任务完成率** | 按类别判定：write 类看数据库是否落库且字段正确；rag 类看回答是否含关键实体 | ≥ 80% |
| **安全拦截率** | safety 类中 `must_not_tools` 未被调用且未落库的占比 | **100%**（这是硬指标） |
| **平均延迟 / P95** | 每轮 wall time | 记录即可 |
| **平均 token 消耗** | 每轮 prompt + completion tokens | 记录即可 |

### 2.3 测试分层（重要：保证可重复）

Agent 评估最大的坑是"模型是随机的，跑两次结果不同"。分两层：

- **Tier 1 — 确定性单测（CI 必跑，秒级）**
  - 用 LangChain 的 `GenericFakeChatModel` 或 monkeypatch `ChatOpenAI`，注入**脚本化的工具调用序列**
  - 校验对象：编排逻辑本身——条件边是否正确路由、工具异常是否被包装成结构化错误回给模型、`recursion_limit` 是否生效、写操作是否被拦截
  - 这部分**不依赖真实 LLM**，所以能进 CI，且结果 100% 稳定
- **Tier 2 — 效果评估（本地 / 手动触发，分钟级）**
  - 打真实 LLM，跑完整 35 条，产出指标表
  - 用 `pytest -m eval` 标记区分，CI 里跳过
  - 结果落盘到 `backend/tests/eval/results/<timestamp>.json`，便于对比历次改动

### 2.4 消融实验（必须做，这是"有数字"的来源）

固定数据集，逐项对比，每一项产出**一行数字**：

1. **检索策略**：纯向量 vs 向量 + BM25 混合检索（`rank_bm25`，对中文先做简单分词）
2. **相似度阈值**：`kb_service.py:91` 的 `score < 0.5` 取值 0.3 / 0.5 / 0.7 三档
3. **是否 rerank**：检索 top10 后接一个 rerank 步骤（可用 LLM 打分或 bge-reranker）对比直接 top2
4. **top-k 截断**：`kb_service.py:97` 的 `[:2]` 取 1 / 2 / 3 / 5
5. **知识库预注入开关**：§1-A 提到的 `KB_PREINJECT` 开 / 关，观察工具选择准确率的差异
6. **System prompt 版本**：当前版本 vs 显式给出工具选择 few-shot 示例的版本

### 2.5 报告的呈现

- 一个脚本 `python -m tests.eval.run` 输出 Markdown 表格到 stdout，可直接贴进 README
- README 里保留**最终一轮的表格**，并注明数据集规模与运行方式
- 简历上写指标时，**必须能解释每个数字的来源和测量方式**——写"Hit Rate@3 从 62% 提升到 89%"就要能回答"数据集怎么造的、k 为什么取 3、怎么判定命中"

### 验收标准

- [ ] `dataset.yaml` 含 ≥ 30 条，五类齐全，`safety` 类 ≥ 8 条
- [ ] `pytest -m eval` 一条命令产出完整指标表
- [ ] `pytest -m "not eval"` 在无 LLM API key 的环境下也能全绿（Tier 1 不依赖网络）
- [ ] 至少完成 §2.4 中 1、2、5 三项消融，有对比数字
- [ ] README 中有一节"评估"，含数据集说明 + 指标表 + 复现命令

**预估**：2-3 天（含数据集编写，这部分是体力活，但价值最高）

---

## 3. 阶段三：写操作硬化 —— 服务端待确认单

**为什么重要**：Agent 岗必问"怎么防止 Agent 误删/误写""怎么防提示词注入"。现在的答案是"prompt 里写了不许"，这是最容易被打穿的防线。

### 设计

**核心原则：LLM 永远不直接写库，`create_lab_reservation` 只产生一条待确认记录。**

新增模型 `PendingAction`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键 |
| `thread_id` | str | 所属会话 |
| `user_id` | int | 发起人（权限校验依据） |
| `tool_name` | str | 目前只有 `create_lab_reservation` |
| `arguments` | JSON/Text | 模型给出的原始参数 |
| `status` | int | 0 待确认 / 1 已执行 / 2 已取消 / 3 已过期 |
| `expire_at` | datetime | 建议 5 分钟 |
| `executed_reservation_id` | int, nullable | 执行成功后回填 |

新增接口：

- `GET /api/ai/pending-actions` — 当前用户待确认列表（前端渲染确认卡片）
- `POST /api/ai/pending-actions/{id}/confirm` — 执行
- `POST /api/ai/pending-actions/{id}/cancel` — 取消

### 执行时的校验顺序（每一步都要能被单测覆盖）

1. `status == 0` 且未过期
2. `user_id == current_user.id`（防越权确认别人的单）
3. 参数重新过一遍 `ReservationCreateRequest` 的 Pydantic 校验
4. 重跑 `reservation_service.create_reservation()` 的全部业务校验

**第 4 步是关键**：不能因为"模型已经查过了"就跳过时间冲突、开放时间、设备状态校验。模型可能在上一次查和这次写之间拿到了过期信息（TOCTOU）。这条也是很好的面试讨论点。

### 流程变化

```
用户："帮我把明天下午2点订上A实验室"
  → 模型调用 create_lab_reservation
  → 工具内部：只写 PendingAction，返回 {"status": "pending_confirmation", "action_id": 12, ...}
  → 模型："即将预约 A实验室（ID 3），明天 14:00-16:00，请确认"
  → 前端渲染确认卡片
  → 用户点确认 → POST /pending-actions/12/confirm → 真正落库
  → 工具返回 {"ok": true, "reservation_id": 88}
```

### 附带收益

- `agent_service.py:31-34` 的 prompt 里那一大段"必须复述""必须等确认"可以大幅简化——约束从 prompt 移到了代码，模型只需负责自然语言交互
- 这正好是 LangGraph `interrupt` 的适用场景。可以先用自建表实现（简单、可控），然后在 README 里说明"为什么没用 `interrupt`：需要跨请求持久化 + 前端主动确认，自建表更直观"。**主动说明取舍比闷头选一个更得分**

### 验收标准

- [ ] 模型调用 `create_lab_reservation` 后，数据库 `reservations` 表**无新增记录**，`pending_actions` 表新增一条
- [ ] 未确认的 pending action 不会在任何路径下落库
- [ ] 用户 A 无法确认用户 B 的 pending action（返回 403）
- [ ] 过期的 pending action 确认失败（返回明确错误码）
- [ ] 参数在确认时被重新校验：手工构造一条"实验室已关闭"的 pending action，确认应失败
- [ ] safety 类评估样本的拦截率达到 100%
- [ ] 前端能展示确认卡片并完成确认/取消

**预估**：1-1.5 天

---

## 4. 阶段四：状态持久化与多轮记忆

**现状问题**：`agent_service.py:82-92` 只用前端传来的纯文本 user/assistant history 重建 messages。这丢失了：
- 工具调用的完整中间态（`tool_calls` / `ToolMessage`）
- 跨轮次的工具调用结果（模型无法引用"我刚才查到的那 3 个实验室"）

### 设计

- 接入 LangGraph checkpointer。起步用 `SqliteSaver`（异步场景用 `AsyncSqliteSaver`），数据落 `backend/data/agent_state.db`
- `ChatRequest` 增加 `thread_id: str | None`（`schemas/ai.py`）。为空则新建，返回给前端
- graph 编译时传 `checkpointer`，调用时传 `config={"configurable": {"thread_id": ...}}`
- **Tool 从 `configurable` 取 `db` / `user`**（与 §1-C 的方案 2 合并实施，一次改造解决两个问题）

### 前端改动

- `frontend/src/views/AIChat.vue`：会话建立时保存 `thread_id`，后续请求携带；切换会话时清空本地消息（历史在服务端）
- 可选的加分项：会话列表 + 切换（能直观演示"记忆生效"）

### 为什么用 checkpointer 而不是自己存 messages（面试必答）

1. **状态 ≠ 消息列表**。graph 的中间态（已执行到哪个节点、待处理的 tool_calls）都在 checkpoint 里，自己存 messages 恢复不了"工具调用执行到一半"的场景
2. **中断续跑的前提**。§3 的待确认机制如果要升级成"图暂停在工具节点、确认后从断点继续"，只有 checkpointer 能做
3. **时间旅行 / 分支调试**。可以回放某次对话的历史 state，排查"模型为什么在这个节点选了这个工具"
4. **总结与裁剪的挂载点**。长对话要做消息摘要压缩时，checkpointer 提供了统一的改造位置

### 验收标准

- [ ] 同一 `thread_id` 下，连续三轮"有哪些实验室" → "第一个有多少设备" → "它的开放时间" 都能正确理解指代
- [ ] 服务重启后继续同一 `thread_id` 对话，上下文不丢
- [ ] 不同 `thread_id` 之间上下文完全隔离（用两个用户交叉验证）
- [ ] `multi_turn` 类评估样本通过率 ≥ 80%

**预估**：1-1.5 天

---

## 5. 阶段五：可观测性 —— 每轮 trace

**为什么重要**：Agent 岗会问"线上 Agent 出错你怎么排查"。有 trace 表能看图回答，没有就只剩"看日志"。

### 设计

新增两张表：

**`agent_traces`**（一轮对话一条）

| 字段 | 说明 |
|---|---|
| `id` / `thread_id` / `user_id` | 归属 |
| `question` | 首轮用户输入（截断存储） |
| `model` | 模型名 |
| `status` | success / error / interrupted |
| `error_message` | 失败原因 |
| `total_latency_ms` | 端到端耗时 |
| `prompt_tokens` / `completion_tokens` | token 用量 |
| `tool_call_count` | 工具调用总数 |

**`agent_trace_steps`**（一步一条）

| 字段 | 说明 |
|---|---|
| `trace_id` / `step_index` | 归属与顺序 |
| `step_type` | llm / tool |
| `name` | 工具名或节点名 |
| `input` / `output` | 截断存储（各限 2000 字符） |
| `latency_ms` | 单步耗时 |
| `status` / `error_message` | 失败定位 |

### 采集方式

- 在 `stream_agent()` 的 `astream_events` 循环里（`agent_service.py:112-143`）已经有完整的 step 边界，顺手记时间戳即可
- **token 用量**：`on_chat_model_end` 事件的 `output.usage_metadata` 里有 `input_tokens` / `output_tokens`，需要确认当前 LangChain 版本是否透出（若不透出，退化方案是用 `get_openai_callback()` 或自建 callback handler）
- 落库要注意：SSE 生成器里拿不到请求级的 DB session 生命周期保证，建议**独立开一个短生命周期 session 写 trace**，或在 `event_gen` 的 `finally` 里统一提交

### 前端

- 新增一个「对话轨迹」页（管理员可见），展示 trace 瀑布图：横轴时间，纵向列出每个 LLM / 工具步骤及其耗时
- 这一页在面试演示时非常有效——**能直观看出"哪一步拖慢了整轮对话"**

### 验收标准

- [ ] 每轮对话产生 1 条 trace + N 条 step
- [ ] trace 里 LLM 步数 = 工具步数 + 1（正常收敛的情况下）
- [ ] 能按 `thread_id` 和 `user_id` 查询
- [ ] 失败轮次记录 `error_message` 且能在前端看到
- [ ] token 用量非空（若版本不支持，需在 README 说明退化方案）

**预估**：1-1.5 天

---

## 6. 加分项（完成主线后按余力选做）

按"面试收益率"排序：

1. **失败降级链** — 模型不可用时退化为纯关键词检索回答；工具抛异常时返回结构化错误让模型自愈（`agent_tools.py` 目前已有雏形：`{"ok": false, "error": ...}`，可以系统化）。面试可答"降级策略"
2. **`recursion_limit=10` 的论证** — `agent_service.py:115` 是魔法数字。压测不同值对完成率与延迟的影响，给出取值依据。**把一个魔法数字变成一个有数据的决策，性价比极高**
3. **并行工具调用** — 模型一轮返回多个 tool_call 时的并发执行与结果聚合，记录串行/并行耗时对比
4. **流式 tool_call 分片聚合** — 部分模型会分片吐出 tool_call 的 arguments，现在的实现是否会正确处理，值得专门验证
5. **消息裁剪 / 摘要压缩** — 长对话超出上下文窗口时的策略，配合 token 统计做效果验证
6. **提示词注入的对抗测试集** — 独立一套红队样本（≥15 条：角色扮演、越权声称、编码绕过、多语言绕过），报告拦截率。这是 safety 方向简历的硬通货
7. **成本核算** — 基于 trace 的 token 数据，估算单轮对话成本，给出优化前后对比

---

## 7. 明确降权 / 不做的部分

投 Agent 岗，以下事项**收益低，不要占用主线时间**：

| 事项 | 现状 | 为什么降权 | 建议处理 |
|---|---|---|---|
| Alembic 迁移 | `main.py:26` 用 `create_all` | 后端工程卫生，Agent 面试官不问 | 一句话带过，不做 |
| Docker / CI | 无 | 同上 | 主线做完有余力再说 |
| 预约并发双开 | `reservation_service.py:88-117` 查-插非原子，无唯一约束 | 是后端并发问题，与 Agent 无关 | **只加一个唯一索引兜底**（`lab_id, equipment_id, date, start_time, end_time`），简历上一句话："乱序/重放的工具调用会导致重复预约，用唯一索引 + 捕获 IntegrityError 兜住"。**不要在 Agent 岗面试里展开这个** |
| 前端路由角色守卫 | `router/index.js:77-85` 只校验 token 存在 | 前端小问题 | 顺手补，10 分钟 |
| `.env` 未进 gitignore | `backend/.gitignore` 缺 `.env`，且 `backend/.env` 已存在 | 安全问题，但只影响仓库整洁 | 补 gitignore，**务必确认 LLM_API_KEY 和 JWT_SECRET_KEY 没进过 git 历史** |
| `.env.example` 缺项 | 缺 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | 会影响可复现性 | 补上（面试官 clone 跑不起来是硬伤） |
| 裸 `print` | `api/ai.py:37,43`、`kb_service.py:95`、`ai_service.py:137` | 代码整洁度 | 删除，改 logger |
| Ollama 硬编码 | `kb_service.py:21-23` 写死 `localhost:11434` 和 `qwen3-embedding:8b` | 影响可复现性 | 抽到 `config.py` 的 settings |
| 无根 README | 后端 README 为 0 字节 | **必须补**，不在降权范围 | 见 §8 |

---

## 8. README 的结构（这是面试官的第一印象，不要凑合）

`README.md` 建议章节：

1. **一句话定位 + 截图/GIF**（30 秒能看懂在做什么）
2. **架构图**（前端 → SSE → FastAPI → LangGraph → 工具 → MySQL / Chroma）
3. **快速开始**（docker-compose 或分步命令，确保能跑起来）
4. **Agent 设计** ← 核心章节，要写清：
   - 为什么选 LangGraph 而不是手写循环
   - 工具设计与参数约束
   - 为什么写操作走"服务端待确认单"而不是 prompt 约束
   - 为什么用 checkpointer（引用 §4 的四条理由）
   - SSE 事件协议（`status` / `tool_start` / `tool_end` / `token` / `done` / `error`）
5. **评估** ← 第二核心章节：
   - 数据集构成表（五类各多少条）
   - 指标定义与最终数字
   - 消融实验对比表
   - 复现命令
6. **可观测性**：trace 表结构 + 轨迹页截图
7. **已知限制与后续计划**：诚实地列出没做的事（如多 Agent 编排、生产级队列、成本控制）。**主动暴露边界比假装完备更显成熟**

---

## 9. 总排期与里程碑

| 阶段 | 内容 | 预估 | 可独立交付 |
|---|---|---|---|
| 一 | 收敛为一套实现 | 0.5 天 | ✅ 做完就能干净讲架构 |
| 二 | 评估集 + 指标 + 消融 | 2-3 天 | ✅ **简历数字的来源，优先做** |
| 三 | 服务端待确认单（agent safety） | 1-1.5 天 | ✅ 可独立成 safety 叙事 |
| 四 | checkpointer 多轮记忆 | 1-1.5 天 | ✅ |
| 五 | trace 可观测性 | 1-1.5 天 | ✅ 含前端轨迹页 |
| 六 | README + 配置整理 + 加分项 | 0.5-1 天 | ✅ |
| — | **合计** | **约 7-9 天** | |

**建议节奏**：一 → 二 → 三 → 六（先形成可投递版本）→ 四 → 五 → 加分项。

理由：阶段一一做完 + 阶段二有数字 + 阶段三有 safety 叙事 + 阶段六有 README，这时**项目已经可以投了**。四和五是在面试流程中持续加分的东西，可以边投边补。

---

## 10. 简历文案（改造完成后）

> **基于 LangGraph 的可执行 Agent 平台（实验室预约域）**
> 独立设计并实现 5 工具编排的 tool-calling Agent，基于 SSE 推送 token 与工具执行事件，前端实时展示推理过程；构建 35 条标注的五类评估集（含 8 条提示词注入红队样本），工具选择准确率 X%、检索 Hit Rate@3 从 A% 提升至 B%（混合检索 + 阈值调优消融验证）；将写操作权限从 prompt 收归代码层，设计服务端待确认单机制，安全类样本拦截率达 100%；接入 checkpointer 实现跨轮次工具上下文续跑；自建 trace 体系记录每步耗时与 token 消耗，定位并优化 P95 延迟 C%

**注意事项**：每个数字都要能答上来源（数据集规模、判定标准、测量方式、运行命令）。数字答不上来比不写数字更糟。

---

## 11. 面试预演问题清单

改造完成后，以下问题应能从容回答——**建议在动手前就先想一遍，很多设计决策是被这些问题倒逼出来的**：

1. 你的 Agent 循环什么时候终止？`recursion_limit=10` 怎么定的？
2. 两套实现为什么合并？手写循环和 LangGraph 各有什么代价？
3. 工具调用失败怎么办？模型能自愈吗？
4. 服务端待确认单和 LangGraph 的 `interrupt` 有什么区别？为什么选前者？
5. 确认时为什么还要重跑一遍业务校验？（TOCTOU）
6. 你怎么防提示词注入？拦截率怎么测的？
7. 检索的 0.5 阈值怎么定的？有没有数据支撑？
8. RAG 为什么用 Chroma + Ollama？换别的会怎样？
9. checkpointer 存了什么？为什么不能自己存 messages？
10. 长对话超出上下文窗口怎么办？
11. 线上 Agent 答错了你怎么排查？（拿 trace 图回答）
12. 你的评估集怎么保证不 overfit？（答案：留出集 + 定期补充真实失败样本）
13. 如果并发量大 100 倍，架构哪里先崩？（诚实回答：`build_agent` 每请求重建、SSE 长连接、Ollama 单点）
14. 这个 Agent 有什么做不到的？（诚实列出边界）
