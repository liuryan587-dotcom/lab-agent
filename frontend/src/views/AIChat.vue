<template>
  <div>
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span style="font-size: 16px; font-weight: bold">AI智能助手</span>
          <el-button size="small" @click="handleNewThread">新会话</el-button>
        </div>
      </template>

      <div
        ref="listRef"
        style="
          height: 480px;
          overflow-y: auto;
          padding: 8px 4px;
          background-color: #fafafa;
          border-radius: 6px;
        "
      >
        <div
          v-for="(item, index) in messages"
          :key="index"
          :style="{
            display: 'flex',
            justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
            marginBottom: '12px'
          }"
        >
          <div
            :style="{
              maxWidth: '70%',
              padding: '10px 12px',
              borderRadius: '8px',
              backgroundColor: item.role === 'user' ? '#409eff' : '#fff',
              color: item.role === 'user' ? '#fff' : '#333',
              lineHeight: '1.6',
              boxShadow: '0 1px 2px rgba(0, 0, 0, 0.06)'
            }"
          >
            <div
              v-if="item.role === 'assistant' && item.status"
              style="margin-bottom: 6px; font-size: 12px; color: #909399"
            >
              {{ item.status }}
            </div>

            <div
              v-if="item.role === 'assistant' && item.steps?.length"
              style="margin-bottom: 8px; font-size: 12px; color: #909399; line-height: 1.5"
            >
              <div v-for="(step, i) in item.steps" :key="i">· {{ step }}</div>
            </div>

            <!-- 待确认单：模型只生成了记录，点确认才真正落库 -->
            <div v-if="item.pending" class="pending-card">
              <div class="pending-head">待确认预约</div>
              <div class="pending-line">
                实验室：{{ item.pending.lab_name || 'ID ' + item.pending.lab_id }}
                <template v-if="item.pending.equipment_name">
                  · 设备：{{ item.pending.equipment_name }}
                </template>
              </div>
              <div class="pending-line">
                时间：{{ item.pending.date }} {{ item.pending.start_time }}–{{ item.pending.end_time }}
              </div>
              <div class="pending-line muted">确认后才会真正提交，5 分钟内有效</div>
              <div v-if="item.pending.status === 0" class="pending-ops">
                <el-button
                  size="small"
                  type="primary"
                  :loading="item.pending.loading"
                  @click="handleConfirm(item)"
                >
                  确认预约
                </el-button>
                <el-button
                  size="small"
                  :disabled="item.pending.loading"
                  @click="handleCancel(item)"
                >
                  取消
                </el-button>
              </div>
              <div
                v-else
                class="pending-result"
                :class="item.pending.status === 1 ? 'ok' : 'muted'"
              >
                {{ item.pending.resultText }}
              </div>
            </div>

            <div class="md-body" v-html="parseMarkdown(item.content)"></div>
          </div>
        </div>
      </div>

      <div style="margin-top: 12px; display: flex; gap: 8px; align-items: flex-end">
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          placeholder="问问实验室怎么预约、开放时间..."
          @keydown.enter.exact.prevent="handleSend"
          @keydown.enter.shift.stop
        ></el-input>
        <el-button type="primary" @click="handleSend" :loading="loading">发送</el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import {
  chatStreamApi,
  listPendingActions,
  confirmPendingAction,
  cancelPendingAction,
  getChatHistory
} from '@/api/ai'
import { ref, reactive, nextTick, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const input = ref('') // 输入框内容
const messages = ref([]) // 消息列表
const loading = ref(false) // 发送中状态
const listRef = ref(null) // 消息列表 DOM 引用
const threadId = ref('') // 服务端分配的会话 id，续接上下文用
const THREAD_KEY = 'lab-agent-thread-id' // 存 localStorage，刷新后能恢复

const scrollToBottom = () => {
  nextTick(() => {
    if (listRef.value) {
      listRef.value.scrollTop = listRef.value.scrollHeight
    }
  })
}
// 大模型返回的是 Markdown（表格、加粗、列表），marked 负责转成 HTML
marked.setOptions({
  gfm: true, // 支持表格、删除线等 GitHub 风格语法
  breaks: true // 单个换行也当换行，聊天场景更符合直觉
})

const parseMarkdown = (text) => {
  if (!text) return ''
  // 必须过 DOMPurify：这里是 v-html 注入，而且内容来自大模型，
  // 大模型又会复述知识库里的文档内容，不消毒等于留了一条 XSS 通道
  return DOMPurify.sanitize(marked.parse(text))
}

const handleSend = async () => {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  scrollToBottom()

  // 必须用 reactive：普通对象 push 后再改字段，视图可能不更新
  const assistant = reactive({
    role: 'assistant',
    content: '', // 正文：靠 token 一点点拼
    status: '正在思考…', // 当前状态文案
    steps: [] // 过程流水，不进下次 history
  })
  messages.value.push(assistant)

  // 会话历史由服务端按 thread_id 保存（含工具调用结果）。
  // 这里只发这一句，不要再把整段历史回传，否则会和服务端的历史重复。
  const payload = { messages: [{ role: 'user', content: text }] }
  if (threadId.value) payload.thread_id = threadId.value

  try {
    // 第二个参数是回调：每解析出一条 SSE 事件就进一次
    await chatStreamApi(payload, (evt) => {
      if (evt.type === 'thread') {
        // 后端分配的会话 id，下一轮带回去才能续上上下文
        threadId.value = evt.thread_id
        localStorage.setItem(THREAD_KEY, evt.thread_id)
      } else if (evt.type === 'status') {
        assistant.status = evt.message || '正在思考…'
      } else if (evt.type === 'tool_start') {
        const label = evt.label || evt.name || '工具'
        assistant.status = `正在${label}…`
        assistant.steps.push(`开始：${label}`)
      } else if (evt.type === 'tool_end') {
        const label = evt.label || evt.name || '工具'
        assistant.status = `${label}完成`
        assistant.steps.push(`完成：${label}`)
      } else if (evt.type === 'pending_action') {
        // 后端说「预约只是生成了待确认单」，这里渲染确认卡片
        assistant.pending = { id: evt.action_id, status: 0, loading: false }
        loadPendingDetail(assistant, evt.action_id)
      } else if (evt.type === 'token') {
        assistant.content += evt.content || '' // 打字机：追加，不是覆盖
        assistant.status = '' // 开始出字后清掉「正在…」，避免叠在一起
      } else if (evt.type === 'done') {
        assistant.status = ''
        // 注意：不要在这里再 append 一整段正文，否则会双份
      } else if (evt.type === 'error') {
        assistant.status = ''
        if (!assistant.content) {
          assistant.content = evt.message || '请求失败'
        }
        ElMessage.error(evt.message || '请求失败')
      }
      scrollToBottom()
    })
  } catch (err) {
    assistant.status = ''
    if (!assistant.content) {
      assistant.content = err.message || '网络异常'
    }
    ElMessage.error(err.message || '网络异常')
  } finally {
    loading.value = false
    assistant.status = ''
    scrollToBottom()
  }
}

// ---------------------------------------------------------------- 待确认单
// 卡片上要展示实验室名称，所以 SSE 只给 action_id，这里再拉一次详情
const loadPendingDetail = async (assistant, actionId) => {
  try {
    const res = await listPendingActions()
    const list = Array.isArray(res?.data) ? res.data : []
    const found = list.find((item) => item.id === actionId)
    if (found && assistant.pending) {
      assistant.pending = { ...assistant.pending, ...found }
    }
  } catch (err) {
    // 以前这里是空 catch：接口 404 / 超时 / 返回 HTML 都看不见，
    // 卡片就静默退化成「实验室：ID undefined、时间：–」。排查时先看这条日志。
    console.warn('[AIChat] 待确认单详情加载失败', err)
  }
}

const handleConfirm = async (message) => {
  const pending = message.pending
  if (!pending || pending.loading) return
  pending.loading = true
  try {
    const res = await confirmPendingAction(pending.id)
    pending.status = 1
    pending.resultText = res?.data?.message || '预约已提交，请等待管理员审核'
    // 界面上补一句「已提交」，让用户看到结果。
    // 注意：真正给模型看的那条记录，是 confirm 接口写进服务端会话历史里的，
    // 不是这里——这里只影响当前页面的显示。
    const record = `\n\n> 已确认并提交：预约号 #${res?.data?.reservation_id}，${pending.resultText}`
    if (!message.content.includes('已确认并提交')) {
      message.content += record
    }
  } catch (err) {
    // 业务校验失败（时段被抢、实验室关闭等）会走到这里
    pending.status = 0
    ElMessage.error(err?.message || '确认失败，请重新发起')
  } finally {
    pending.loading = false
  }
}

const handleCancel = async (message) => {
  const pending = message.pending
  if (!pending || pending.loading) return
  pending.loading = true
  try {
    await cancelPendingAction(pending.id)
    pending.status = 2
    pending.resultText = '已取消，不会提交预约'
  } catch (err) {
    ElMessage.error(err?.message || '取消失败')
  } finally {
    pending.loading = false
  }
}

// ---------------------------------------------------------------- 会话恢复
// threadId 存 localStorage。onMounted 时把消息和未确认的卡片拉回来。
// localStorage 里的三种状态：
//   null  —— 从没用过，退回到「最近一次会话」
//   ''    —— 用户点过「新会话」，别再自动恢复
//   其它  —— 具体会话 id
onMounted(async () => {
  const saved = localStorage.getItem(THREAD_KEY)
  if (saved === '') return // 用户明确要新会话

  try {
    const res = await getChatHistory(saved || undefined)
    const data = res?.data || {}
    const restored = data.messages || []
    const pendings = data.pending_actions || []

    if (!data.thread_id || (!restored.length && !pendings.length)) {
      localStorage.removeItem(THREAD_KEY)
      return
    }

    threadId.value = data.thread_id
    localStorage.setItem(THREAD_KEY, data.thread_id)
    messages.value = restored.map((item) => ({
      role: item.role,
      content: item.content,
      steps: []
    }))
    for (const action of pendings) {
      messages.value.push({
        role: 'assistant',
        content: '',
        steps: [],
        pending: { ...action, loading: false }
      })
    }
    scrollToBottom()
  } catch (err) {
    // 常见原因：后端没重启（404）、登录失效。保留 localStorage，修好后再刷新还能恢复
    console.error('[AIChat] 恢复会话失败', err)
  }
})

const handleNewThread = () => {
  messages.value = []
  threadId.value = ''
  // 空字符串 = 用户主动开新会话，下次刷新不要再自动恢复旧对话
  localStorage.setItem(THREAD_KEY, '')
}
</script>

<style scoped>
/* 大模型输出的 Markdown 渲染进 .md-body，
   v-html 生成的节点不带 scoped 属性，所以必须用 :deep() 才能命中 */
.md-body {
  overflow-x: auto; /* 表格过宽时横向滚动，不撑破气泡 */
  word-break: break-word;
}

.md-body :deep(p) {
  margin: 6px 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 6px 0;
  padding-left: 20px;
}

.md-body :deep(li) {
  margin: 2px 0;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  margin: 10px 0 6px;
  font-size: 14px;
  font-weight: 600;
}

/* 表格：Element Plus 不会给原生 table 加样式，这里自己补 */
.md-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 12px;
}

.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 4px 8px;
  text-align: left;
}

.md-body :deep(th) {
  background-color: #f5f7fa;
  font-weight: 600;
}

.md-body :deep(tbody tr:nth-child(even) td) {
  background-color: #fafafa;
}

.md-body :deep(code) {
  background-color: #f5f7fa;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.md-body :deep(pre) {
  background-color: #f5f7fa;
  padding: 8px 10px;
  border-radius: 4px;
  overflow-x: auto;
  margin: 8px 0;
}

.md-body :deep(pre code) {
  background: none;
  padding: 0;
}

.md-body :deep(blockquote) {
  margin: 6px 0;
  padding-left: 10px;
  border-left: 3px solid #dcdfe6;
  color: #606266;
}

.md-body :deep(a) {
  color: #409eff;
  text-decoration: none;
}

.md-body :deep(hr) {
  border: none;
  border-top: 1px solid #ebeef5;
  margin: 10px 0;
}

/* 待确认卡片：模型只生成待确认记录，用户点确认才真正落库 */
.pending-card {
  margin: 8px 0 10px;
  padding: 10px 12px;
  border: 1px solid #ffd591;
  background: #fffbe6;
  border-radius: 6px;
  font-size: 13px;
}

.pending-head {
  font-weight: 600;
  color: #ad6800;
  margin-bottom: 6px;
}

.pending-line {
  line-height: 1.7;
  color: #333;
}

.pending-line.muted {
  color: #909399;
  font-size: 12px;
}

.pending-ops {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.pending-result {
  margin-top: 6px;
  font-size: 12px;
}

.pending-result.ok {
  color: #67c23a;
}

.pending-result.muted {
  color: #909399;
}
</style>
