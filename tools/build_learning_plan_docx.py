from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor


OUT = Path("output/docx/Python与AI Agent面试知识体系学习计划.docx")


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_cell_margins(cell, top=100, start=120, bottom=100, end=120):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def set_table_borders(table, color="D9D9D9", size="6"):
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.first_child_found_in("w:tblBorders")
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = borders.find(qn(f"w:{edge}"))
        if tag is None:
            tag = OxmlElement(f"w:{edge}")
            borders.append(tag)
        tag.set(qn("w:val"), "single")
        tag.set(qn("w:sz"), size)
        tag.set(qn("w:color"), color)


def set_repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_font(run, name="Microsoft YaHei", size=10, bold=None, color="000000"):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def add_page_field(paragraph):
    run = paragraph.add_run()
    fld_char1 = OxmlElement("w:fldChar")
    fld_char1.set(qn("w:fldCharType"), "begin")
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    fld_char2 = OxmlElement("w:fldChar")
    fld_char2.set(qn("w:fldCharType"), "end")
    run._r.append(fld_char1)
    run._r.append(instr_text)
    run._r.append(fld_char2)
    set_font(run, size=8.5, color="666666")


def style_table(table, widths=None):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_borders(table)
    set_repeat_table_header(table.rows[0])
    for r_idx, row in enumerate(table.rows):
        if r_idx > 0 and r_idx % 2 == 0:
            for cell in row.cells:
                set_cell_shading(cell, "F2F6FA")
        for c_idx, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            set_cell_margins(cell)
            if widths:
                cell.width = widths[c_idx]
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.line_spacing = 1.15
                if c_idx == 0 and r_idx > 0:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in p.runs:
                    set_font(run, size=9.2)
    for cell in table.rows[0].cells:
        set_cell_shading(cell, "264A66")
        for p in cell.paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                set_font(run, size=9.2, bold=True, color="FFFFFF")


def add_bullets(doc, items, level=0):
    for item in items:
        p = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.left_indent = Cm(0.65 + level * 0.45)
        p.paragraph_format.first_line_indent = Cm(-0.35)
        r = p.add_run(item)
        set_font(r)


def add_checklist(doc, items):
    for item in items:
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Cm(0.4)
        p.paragraph_format.first_line_indent = Cm(-0.4)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(f"□ {item}")
        set_font(r)


def add_week(doc, title, topics, practice, questions=None):
    p = doc.add_paragraph(style="Heading 3")
    p.paragraph_format.keep_with_next = True
    r = p.add_run(title)
    set_font(r, size=12, bold=True)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run("学习重点  ")
    set_font(r, bold=True)
    r = p.add_run("、".join(topics))
    set_font(r)

    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run("动手任务  ")
    set_font(r, bold=True)
    r = p.add_run(practice)
    set_font(r)

    if questions:
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run("题库范围  ")
        set_font(r, bold=True)
        r = p.add_run(questions)
        set_font(r)


def add_phase(doc, number, title, weeks, objective, week_data, acceptance, milestone):
    doc.add_page_break()
    p = doc.add_paragraph(style="Heading 1")
    r = p.add_run(f"阶段 {number}  {title}")
    set_font(r, size=18, bold=True)

    p = doc.add_paragraph()
    r = p.add_run(f"周期  第 {weeks} 周")
    set_font(r, size=10, bold=True, color="35566F")

    p = doc.add_paragraph(objective)
    p.paragraph_format.space_after = Pt(8)
    for run in p.runs:
        set_font(run)

    for data in week_data:
        add_week(doc, *data)

    p = doc.add_paragraph(style="Heading 2")
    r = p.add_run("阶段验收")
    set_font(r, size=14, bold=True)
    add_checklist(doc, acceptance)

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    r = p.add_run("项目里程碑  ")
    set_font(r, bold=True)
    r = p.add_run(milestone)
    set_font(r)


doc = Document()
section = doc.sections[0]
section.top_margin = Cm(1.85)
section.bottom_margin = Cm(1.65)
section.left_margin = Cm(2.2)
section.right_margin = Cm(2.2)

styles = doc.styles
normal = styles["Normal"]
normal.font.name = "Microsoft YaHei"
normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
normal.font.size = Pt(10)
normal.font.color.rgb = RGBColor(0, 0, 0)
normal.paragraph_format.line_spacing = 1.23
normal.paragraph_format.space_after = Pt(4)

for name, size, before, after in (
    ("Title", 25, 0, 12),
    ("Heading 1", 18, 14, 8),
    ("Heading 2", 14, 10, 5),
    ("Heading 3", 12, 8, 3),
):
    style = styles[name]
    style.font.name = "Microsoft YaHei"
    style._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    style.font.size = Pt(size)
    style.font.bold = True
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.paragraph_format.space_before = Pt(before)
    style.paragraph_format.space_after = Pt(after)
    style.paragraph_format.keep_with_next = True

# Remove the border carried by some Word built-in Title styles.
title_ppr = styles["Title"]._element.get_or_add_pPr()
title_border = title_ppr.find(qn("w:pBdr"))
if title_border is not None:
    title_ppr.remove(title_border)

# Cover
p = doc.add_paragraph(style="Title")
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(90)
r = p.add_run("Python 与 AI Agent 面试学习计划")
set_font(r, size=21, bold=True)

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(10)
r = p.add_run("知识体系重建 28 周循序学习与项目实践手册")
set_font(r, size=14, color="4D4D4D")

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(38)
r = p.add_run("适用目标")
set_font(r, size=11, bold=True)

for line in (
    "从基础薄弱开始重新建立知识体系",
    "完成贯穿 Python 后端与 AI Agent 的综合项目",
    "能够独立回答面试题库中的绝大部分问题",
):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(line)
    set_font(r, size=10.5, color="333333")

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(65)
r = p.add_run("建议投入  每周 12 至 15 小时")
set_font(r, size=10, bold=True, color="35566F")

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("版本  2026 年 10 月")
set_font(r, size=9, color="777777")

doc.add_page_break()

# Introduction
p = doc.add_paragraph(style="Heading 1")
r = p.add_run("如何使用这份计划")
set_font(r, size=18, bold=True)

intro = (
    "这份计划面向基础薄弱、知识零散的学习者。核心方法是先建立 Python 和后端基础，"
    "再进入数据库、框架、基础设施、大模型和 Agent，最后通过一个持续迭代的项目把知识串起来。"
    "完成全部阶段后，目标是能够解释原理、编写代码、举出项目案例，并说明技术的适用边界。"
)
p = doc.add_paragraph(intro)
for run in p.runs:
    set_font(run)

p = doc.add_paragraph()
r = p.add_run("执行原则  ")
set_font(r, bold=True)
r = p.add_run("不要从第 1 题背到第 800 题。每次先学习知识，再动手实现，最后用题库检验是否掌握。")
set_font(r)

add_checklist(doc, [
    "按周完成学习主题、最小代码实验和项目任务",
    "每周随机口述 20 道题，错题在 1 天、7 天、30 天后复习",
    "每个阶段完成验收，不满足标准时先补缺再进入下一阶段",
])

p = doc.add_paragraph(style="Heading 2")
r = p.add_run("最终项目")
set_font(r, size=14, bold=True)
p = doc.add_paragraph(
    "全程构建一个支持用户登录、文档上传、RAG 问答、工具调用、会话记忆、流式输出、"
    "权限控制和日志监控的 AI Agent 服务。每个阶段都为该系统增加一部分能力。"
)
for run in p.runs:
    set_font(run)

p = doc.add_paragraph(style="Heading 2")
r = p.add_run("阶段总览")
set_font(r, size=14, bold=True)

overview = [
    ("1", "Python 基础", "1 至 5", "1 至 96", "能够熟练编写 Python"),
    ("2", "并发 网络与 Web", "6 至 8", "97 至 160", "理解后端程序如何运行"),
    ("3", "PostgreSQL", "9 至 11", "721 至 800", "掌握数据建模与 SQL"),
    ("4", "FastAPI", "12 至 15", "161 至 260", "开发可测试的 API 服务"),
    ("5", "Redis 与 Nginx", "16 至 18", "561 至 720", "掌握缓存 网关和部署"),
    ("6", "大模型基础", "19 至 21", "431 至 560", "理解 LLM 与推理链路"),
    ("7", "RAG 与 Agent", "22 至 25", "261 至 430", "开发可靠的 Agent"),
    ("8", "综合项目", "26 至 27", "全部模块", "打通完整技术栈"),
    ("9", "面试训练", "28", "全部题目", "形成个人答案体系"),
]
table = doc.add_table(rows=1, cols=5)
for idx, text in enumerate(("阶段", "主题", "周数", "题库范围", "结果")):
    table.rows[0].cells[idx].text = text
for row in overview:
    cells = table.add_row().cells
    for idx, text in enumerate(row):
        cells[idx].text = text
style_table(table, [Cm(1.2), Cm(3.2), Cm(2.0), Cm(2.7), Cm(6.0)])

# Phase data
add_phase(doc, 1, "Python 基础", "1 至 5", "先建立稳定的语言基础。此阶段不追求框架数量，而是确保能独立完成常见编程任务并解释 Python 的核心机制。", [
    ("第 1 周  语法与数据类型", ["变量和表达式", "字符串", "list tuple dict set", "条件和循环", "推导式", "可变与不可变对象", "is 与等号", "切片 排序和哈希"], "完成文本词频统计器、日期计算器和日志编码转换程序。", "1 至 30"),
    ("第 2 周  函数与模块", ["参数传递", "作用域和 LEGB", "args 与 kwargs", "lambda 和闭包", "迭代器和生成器", "装饰器", "模块 包 虚拟环境"], "实现计时、重试、缓存三个装饰器，以及分块读取大文件的生成器。", "31 至 60"),
    ("第 3 周  面向对象", ["类和实例", "继承与组合", "类方法和静态方法", "魔术方法", "抽象类和协议", "属性访问", "浅拷贝与深拷贝"], "设计一个拥有统一名称、参数和执行接口的工具插件系统。", "61 至 96"),
    ("第 4 周  异常 文件与工程规范", ["异常体系", "try except else finally", "上下文管理器", "pathlib 和 JSON", "日志", "类型注解", "dataclass", "pytest"], "为插件系统加入结构化日志、异常处理和单元测试。", None),
    ("第 5 周  Python 原理", ["对象引用", "引用计数", "循环引用", "垃圾回收", "哈希表", "GIL", "CPython PyPy Cython Numba", "时间和空间复杂度"], "使用小实验观察对象引用、线程执行和垃圾回收行为。", None),
], [
    "不看资料实现装饰器、生成器和上下文管理器",
    "能够解释可变对象、闭包、GIL 和垃圾回收",
    "题目 1 至 96 的随机抽查正确率达到 70%",
], "完成可扩展的 Python 工具插件系统。")

add_phase(doc, 2, "并发 网络与 Web", "6 至 8", "理解代码如何在操作系统、网络和 Web 服务中运行，为后续异步 FastAPI 和 Agent 工具调用打下基础。", [
    ("第 6 周  进程 线程与协程", ["进程和线程", "竞态条件", "锁和死锁", "线程安全", "multiprocessing", "concurrent futures", "asyncio", "事件循环", "CPU 密集与 IO 密集"], "分别使用串行、线程池、进程池和 asyncio 处理同一批任务并比较性能。", "97 至 113"),
    ("第 7 周  网络基础", ["OSI 和 TCP IP", "TCP 与 UDP", "握手与挥手", "TIME WAIT", "DNS", "URL", "Socket", "HTTP", "HTTPS TLS 和证书"], "编写简单 Socket 客户端和服务端，并通过日志观察一次 HTTP 请求。", "114 至 128"),
    ("第 8 周  Web 基础", ["WSGI 和 ASGI", "Cookie Session JWT", "CORS 与 CSRF", "认证和授权", "MVC", "ORM", "中间件", "Django Flask FastAPI 定位"], "实现一个最小 Web 服务，加入登录状态和请求日志。", "129 至 160"),
], [
    "能够区分同步异步、并发并行、阻塞非阻塞",
    "能够完整描述浏览器访问一个 URL 的过程",
    "能根据任务性质选择线程、进程或协程",
    "题目 97 至 160 的随机抽查正确率达到 70%",
], "建立具备并发任务能力的最小 Web 服务。")

add_phase(doc, 3, "PostgreSQL", "9 至 11", "先学会正确保存和查询业务数据，再学习事务、索引和生产运维。", [
    ("第 9 周  SQL 与数据建模", ["表和字段", "主键和外键", "约束", "增删改查", "JOIN", "GROUP BY", "子查询", "CTE", "窗口函数", "NULL", "JSONB", "数据库范式"], "为 Agent 服务设计用户、文档、会话、消息和工具调用表，并编写至少 30 条 SQL。", "721 至 724 以及 732 至 738"),
    ("第 10 周  事务与索引", ["ACID", "隔离级别", "MVCC", "锁和死锁", "乐观锁与悲观锁", "B tree Hash GIN GiST", "EXPLAIN ANALYZE"], "制造并分析一次死锁，为慢查询添加索引并比较执行计划。", "725 至 731 以及 739 至 745"),
    ("第 11 周  生产运维", ["VACUUM 和 ANALYZE", "连接池", "备份恢复", "WAL 和 PITR", "复制和高可用", "分区表", "批量写入", "pgvector"], "完成数据库迁移、备份恢复演练，并实现一个向量相似度查询。", "746 至 800"),
], [
    "能够独立设计 Agent 业务数据表",
    "能够解释事务、MVCC、索引和慢查询",
    "能够使用 EXPLAIN ANALYZE 给出优化依据",
    "题目 721 至 800 的随机抽查正确率达到 70%",
], "完成 Agent 服务数据库和向量检索基础。")

add_phase(doc, 4, "FastAPI", "12 至 15", "把 Python、异步、HTTP 和数据库知识组合成可测试、可维护的 API 服务。", [
    ("第 12 周  基本 API", ["路由和请求方法", "路径查询和请求体参数", "Pydantic", "响应模型", "状态码", "参数校验", "异常处理", "OpenAPI 和 Swagger"], "实现用户、文档、会话和消息的 CRUD 接口。", "161 至 183"),
    ("第 13 周  项目结构", ["APIRouter", "依赖注入", "配置管理", "SQLAlchemy", "Alembic", "数据库 Session", "Service 和 Repository 分层"], "将项目拆分为路由、模型、服务、仓储和配置模块。", "184 至 188 以及 203 至 220"),
    ("第 14 周  异步与高级功能", ["async SQLAlchemy", "文件上传下载", "BackgroundTasks", "WebSocket", "SSE", "StreamingResponse", "应用生命周期"], "增加文档上传、后台解析和 SSE 流式聊天接口。", "189 至 209 以及 226 至 233"),
    ("第 15 周  安全 测试与生产化", ["JWT OAuth2 RBAC", "密码哈希", "限流", "幂等", "重试", "TestClient", "pytest", "结构化日志", "request ID", "健康检查", "优雅关闭"], "完成认证授权、测试、日志追踪和生产运行配置。", "221 至 225 以及 234 至 260"),
], [
    "能够独立从零搭建分层 FastAPI 项目",
    "能够实现认证、数据库访问、流式输出和异常处理",
    "关键接口具备自动测试",
    "题目 161 至 260 的随机抽查正确率达到 75%",
], "完成可登录、可上传文档、可流式聊天的 FastAPI 服务。")

add_phase(doc, 5, "Redis 与 Nginx", "16 至 18", "学习生产环境中的缓存、限流、持久化、反向代理和流量治理。", [
    ("第 16 周  Redis 数据结构与缓存", ["String Hash List Set ZSet", "TTL", "缓存穿透", "缓存击穿", "缓存雪崩", "淘汰策略", "热点 Key 和大 Key"], "缓存用户会话和查询结果，实现随机 TTL 与空值缓存。", "621 至 636"),
    ("第 17 周  Redis 可靠性与分布式能力", ["RDB 和 AOF", "Pipeline", "事务", "Lua", "分布式锁", "Pub Sub 和 Stream", "Sentinel", "Cluster", "慢查询"], "实现滑动窗口限流、分布式锁和延迟任务队列。", "637 至 720"),
    ("第 18 周  Nginx", ["Master Worker", "反向代理", "负载均衡", "upstream", "keepalive", "TLS", "HTTP 2", "WebSocket 与 SSE", "静态缓存", "限流和日志"], "使用 Nginx 代理 FastAPI，配置 HTTPS、SSE、限流和静态文件缓存。", "561 至 620"),
], [
    "能够为不同业务选择合适的 Redis 数据结构",
    "能够解释缓存常见故障和数据一致性方案",
    "能够配置 Nginx 代理、TLS、流式连接和限流",
    "Redis 与 Nginx 题目随机抽查正确率达到 70%",
], "获得可通过 Nginx 对外服务并具备缓存与限流能力的系统。")

add_phase(doc, 6, "大模型基础", "19 至 21", "理解大模型应用背后的关键概念，能够分析质量、延迟、吞吐量和成本。", [
    ("第 19 周  模型原理", ["Token 和分词", "Embedding", "Transformer", "Attention", "Query Key Value", "位置编码", "预训练", "SFT", "RLHF 和 DPO"], "手工计算一个简化的向量相似度示例，并绘制一次 Transformer 数据流。", "431 至 458"),
    ("第 20 周  生成与应用", ["Temperature", "Top p 和 Top k", "上下文窗口", "幻觉", "知识截止", "Prompt", "few shot", "结构化输出", "Function Calling", "评估"], "调用模型完成流式问答，并让输出通过 Pydantic Schema 校验。", "459 至 500"),
    ("第 21 周  推理与 LLMOps", ["KV Cache", "量化", "LoRA", "Batch", "吞吐量与延迟", "TTFT", "vLLM", "模型服务", "监控", "成本和安全"], "记录每次模型调用的 token、首字延迟、总延迟、成本和错误率。", "501 至 560"),
], [
    "能够解释 Token、Embedding、Transformer 和 Attention",
    "能够说明采样参数怎样影响输出",
    "能够分析模型服务的质量、延迟、吞吐量和成本",
    "题目 431 至 560 的随机抽查正确率达到 70%",
], "完成具备结构化输出、流式响应和调用指标记录的模型服务层。")

add_phase(doc, 7, "RAG 与 Agent", "22 至 25", "从检索增强开始，逐步加入工具调用、状态管理、评估和安全控制，构建可恢复、可观察的 Agent。", [
    ("第 22 周  RAG", ["文档解析和清洗", "切分", "Embedding", "向量数据库", "相似度检索", "混合检索", "Query Rewrite", "HyDE", "Rerank", "Recall MRR NDCG Faithfulness"], "完成 PDF 文档入库、混合检索、重排和带引用的回答。", "271 至 277 以及 301 至 311"),
    ("第 23 周  Agent 基础", ["Agent 与普通 LLM 应用", "ReAct", "Planning", "工具调用", "短期与长期记忆", "状态管理", "执行循环", "终止条件"], "为系统增加搜索、数据库查询和文件读取工具，并控制最大执行步数。", "261 至 270 以及 278 至 300"),
    ("第 24 周  Agent 框架与协议", ["LangChain Runnable", "LCEL", "LangGraph 状态节点和边", "Checkpoint", "MCP Client Server Tool Resource", "多 Agent 边界"], "使用 LangGraph 重构工作流，实现暂停、恢复和失败重试。", "286 至 315 以及 328 至 333"),
    ("第 25 周  可靠性与安全", ["Prompt Injection", "最小权限", "沙箱", "Human in the loop", "超时重试熔断降级", "Trace", "评估和回放", "A B 测试", "成本预算"], "为高风险工具加入人工审批，并建立 Agent 测试集和回归评估。", "316 至 430"),
], [
    "能够设计并解释完整 RAG 链路",
    "能够说明 Agent 的状态、工具、记忆和终止条件",
    "能够处理注入攻击、错误工具调用、超时和恢复",
    "题目 261 至 430 的随机抽查正确率达到 75%",
], "完成可检索、可调用工具、可恢复、可评估的 AI Agent。")

add_phase(doc, 8, "综合项目", "26 至 27", "将各模块组合为一个能够部署、测试和演示的完整系统。重点不是增加更多框架，而是补齐链路、边界和运维能力。", [
    ("第 26 周  功能打通", ["FastAPI API", "PostgreSQL 和 pgvector", "Redis", "文档入库", "RAG", "工具调用", "SSE", "JWT 和 RBAC"], "从用户请求开始，打通检索、模型生成、工具执行、数据保存和流式响应。", "综合复习"),
    ("第 27 周  生产化与演示", ["Nginx", "日志和 Trace", "token 与成本", "超时和重试", "幂等", "降级", "pytest", "部署说明", "故障演练"], "编写 README、架构说明、接口文档和演示脚本，完成至少三次故障演练。", "综合复习"),
], [
    "新环境可以按 README 启动项目",
    "主流程有自动测试和结构化日志",
    "能够演示正常流程、失败重试和人工审批",
    "能够讲清架构选择、性能、安全和成本边界",
], "形成一个可以用于简历和面试演示的完整项目。")

add_phase(doc, 9, "面试训练", "28", "把已经掌握的知识组织成清晰、可追问、带项目证据的个人答案。", [
    ("第 28 周  模拟面试与查漏补缺", ["随机抽题", "限时口述", "追问", "代码题", "系统设计", "项目复盘", "错题回炉"], "每天口述 30 题；完成 3 次 60 分钟模拟面试；修订答案卡片和项目故事。", "全部题目"),
], [
    "一分钟内给出结构化回答",
    "回答中包含原理、场景和边界，而非只背定义",
    "能够现场编写常见 Python、SQL 和 FastAPI 代码",
    "能够完整讲述五个项目故事",
    "全题库随机抽查正确率达到 80% 以上",
], "形成个人面试答案库和可重复演练的项目讲解。")

# Execution templates
doc.add_page_break()
p = doc.add_paragraph(style="Heading 1")
r = p.add_run("每周执行节奏")
set_font(r, size=18, bold=True)

schedule = [
    ("周一", "学习新概念", "阅读文档并制作概念卡片", "2 至 2.5 小时"),
    ("周二", "最小代码实验", "用最少代码验证原理", "2 至 2.5 小时"),
    ("周三", "继续学习和编码", "处理边界条件和常见错误", "2 至 2.5 小时"),
    ("周四", "题库练习", "先独立回答 再对照修正", "2 小时"),
    ("周五", "知识整理", "更新知识图和错题表", "1 至 1.5 小时"),
    ("周六", "项目开发", "完成本周项目功能", "3 至 4 小时"),
    ("周日", "测试和复盘", "随机口述 20 题并制定下周计划", "2 小时"),
]
table = doc.add_table(rows=1, cols=4)
for idx, text in enumerate(("日期", "重点", "行动", "建议时间")):
    table.rows[0].cells[idx].text = text
for row in schedule:
    cells = table.add_row().cells
    for idx, text in enumerate(row):
        cells[idx].text = text
style_table(table, [Cm(1.7), Cm(3.2), Cm(7.7), Cm(2.5)])

p = doc.add_paragraph(style="Heading 2")
r = p.add_run("每周必须留下的成果")
set_font(r, size=14, bold=True)
add_checklist(doc, [
    "一篇自己的知识总结",
    "一组能够运行的代码和测试",
    "一张更新后的知识结构图",
    "一份本周错题表",
    "一次口述录音或模拟面试记录",
])

doc.add_page_break()
p = doc.add_paragraph(style="Heading 2")
r = p.add_run("单题回答模板")
set_font(r, size=14, bold=True)
answer_rows = [
    ("1", "结论", "用一句话直接回答问题"),
    ("2", "原理", "说明核心机制和关键流程"),
    ("3", "比较", "与容易混淆的概念进行区分"),
    ("4", "项目", "给出自己项目中的使用方式"),
    ("5", "边界", "说明风险 限制 失败模式和取舍"),
]
table = doc.add_table(rows=1, cols=3)
for idx, text in enumerate(("步骤", "内容", "要求")):
    table.rows[0].cells[idx].text = text
for row in answer_rows:
    cells = table.add_row().cells
    for idx, text in enumerate(row):
        cells[idx].text = text
style_table(table, [Cm(1.4), Cm(2.7), Cm(10.7)])

p = doc.add_paragraph(style="Heading 2")
r = p.add_run("五个必须准备的项目故事")
set_font(r, size=14, bold=True)
add_checklist(doc, [
    "为什么选择当前架构和技术栈",
    "遇到过什么故障 如何定位和修复",
    "如何减少幻觉和错误工具调用",
    "如何优化延迟 吞吐量和成本",
    "如何保证权限 安全和数据隔离",
])

doc.add_page_break()
p = doc.add_paragraph(style="Heading 1")
r = p.add_run("周复盘记录模板")
set_font(r, size=18, bold=True)

review_items = [
    ("本周周次", "第        周"),
    ("完成日期", "        年        月        日"),
    ("完成内容", ""),
    ("能够独立解释的知识", ""),
    ("已经完成的代码", ""),
    ("仍然模糊的问题", ""),
    ("题库抽查", "抽取        题  正确        题  正确率        %"),
    ("下周优先任务", ""),
]
table = doc.add_table(rows=0, cols=2)
for label, value in review_items:
    cells = table.add_row().cells
    cells[0].text = label
    cells[1].text = value + ("\n" if label in {"完成内容", "能够独立解释的知识", "已经完成的代码", "仍然模糊的问题", "下周优先任务"} else "")
style_table(table, [Cm(3.4), Cm(11.4)])
for cell in table.columns[0].cells:
    set_cell_shading(cell, "E8EFF5")
    for p in cell.paragraphs:
        for run in p.runs:
            set_font(run, size=9.5, bold=True)

p = doc.add_paragraph(style="Heading 2")
r = p.add_run("掌握程度判断")
set_font(r, size=14, bold=True)
add_checklist(doc, [
    "我能不看资料解释它",
    "我能写出最小可运行示例",
    "我能说出它解决了什么问题",
    "我能给出一个真实项目场景",
    "我能说明至少一个限制或失败模式",
])

# Footer
for section in doc.sections:
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Python 与 AI Agent 面试知识体系学习计划   ")
    set_font(r, size=8.5, color="777777")
    add_page_field(p)

doc.core_properties.title = "Python 与 AI Agent 面试知识体系学习计划"
doc.core_properties.subject = "28 周循序学习与项目实践计划"
doc.core_properties.keywords = "Python, FastAPI, AI Agent, RAG, PostgreSQL, Redis, Nginx, 面试"

OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(OUT.resolve())
