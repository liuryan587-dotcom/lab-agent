# 多轮记忆与 Trace

## 问题

改造前，前端只回传 `{role, content}` 的纯文本，服务端每轮重建消息：

```
前端 messages[]  →  只留 user/assistant 文本  →  _build_history 重建
                            ↑
                    tool_calls / ToolMessage 全丢
```

后果很具体：模型第一轮查了「人工智能实验室的设备」，第二轮问「显卡那台的规格」时，
它看不到上一轮查回来的列表，只能**重新调一次工具**。

这不是模型笨，是**对话没有状态**。

## 方案：服务端按 thread_id 存完整消息

不使用 LangGraph 的 checkpointer。原因：

- 这个产品需要的是「跨请求记得上一轮查到了什么」，不是「图执行到一半能续跑」
- checkpointer 要引入 `langgraph-checkpoint-sqlite` 新依赖，而项目的 `pyproject.toml`
  还没声明 `langgraph` / `langchain-openai`，`uv add` 会先做精确同步把它们卸载
- 自己存一张表，多 100 行代码，换来完全可控

### 表结构

`chat_messages`：

| 字段 | 说明 |
|---|---|
| thread_id | 会话 id，前端第一次不传、后端生成并通过 SSE `thread` 事件返回 |
| user_id | 归属用户，读历史时按它过滤（别人的会话读不到） |
| role | user / assistant / tool |
| content | 正文 |
| payload | JSON：assistant 存 `tool_calls`，tool 存 `tool_call_id` / `name` |

**关键点是 `tool` 消息也要存。** 少存这一种，模型就又回到"什么都没查到"的状态。

### 一轮对话的流程

```
1. 前端只发这一句 + thread_id
2. 后端 load 历史（含 tool 消息）→ [*history, HumanMessage]
3. 跑图，astream_events 推 SSE
4. on_chain_end 拿到最终 state，切出本轮新增消息
5. 落库 + 落 trace
```

第 4 步的切片下标是 `final_messages[len(messages_in):]`——
`inputs = [system] + messages_in`，最后一条用户消息正好在 `len(messages_in)` 这个位置。

### 前端改动

- 保存 `threadId`，每轮带上
- **不再回传整段历史**（否则会和服务端的历史重复）

## Trace

两张表：

- `agent_traces`：一轮一条，记录问题、模型、状态、总耗时、token、工具调用数、错误信息
- `agent_trace_steps`：一次工具调用一条，记录名称、入参、出参、耗时、状态

写入位置在 `stream_agent` 的 `finally` 里——无论成功、失败还是客户端断开，都会留痕。

查询接口：`GET /api/ai/traces?limit=20`

## 实测

两轮对话（`人工智能实验室有哪些设备？` → `显卡那台的规格是什么？`）：

| | 工具调用 | 耗时 | prompt tokens |
|---|---|---|---|
| 第一轮 | 1 次（list_lab_equipments） | 2478 ms | 2883 |
| 第二轮 | **0 次** | 1758 ms | 1666 |

第二轮直接答出「RTX5090 24G」，没有重新查——因为历史里有第一轮那条 ToolMessage。

## 刷新恢复

`threadId` 存在 `localStorage`，刷新页面后调用 `GET /api/ai/history?thread_id=`：

```json
{
  "thread_id": "t1a2b3c4",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "pending_actions": [
    {"id": 1, "lab_name": "人工智能实验室", "date": "2026-10-29",
     "start_time": "14:00", "end_time": "16:00", "status": 0}
  ]
}
```

两个细节：

- **只返回有正文的 user/assistant 消息**。带 `tool_calls` 的那条 assistant 是空正文，
  给模型用的，恢复界面时不该出现空白气泡。
- **未确认的卡片一起返回**，前端按会话补一条消息接上，刷新后还能继续点确认。

页面头部加了「新会话」按钮，清空 `messages` + `threadId` + `localStorage`。

## 已知限制

1. **历史是全量回放**：`MAX_HISTORY_MESSAGES = 40`，超出直接截断，没有做摘要压缩。
   长对话会丢早期上下文。
2. **没有做 checkpoint 的语义**：工具执行到一半中断，无法从中断点续跑。
3. **恢复的是文本，不是过程**：刷新后能看到问答，但看不到当时那些「查询实验室设备」的过程行。
