# docs 索引

> ⚠️ 这份文件是「索引」，不要当作学习计划。**学习计划以你自己写的那两份为准。**

## 已有的计划文档（这才是主线）

| 文件 | 管什么 | 什么时候看 |
|---|---|---|
| [学习路线.md](学习路线.md) | **工程主线**：L1–L5 五级进阶，每一级有掌握点 / 常见错误 / 练习 / 晋级标准 | 定方向时看 |
| [L1-学习计划.md](L1-学习计划.md) | **当前该做什么**：8 天 × 8 小时的逐日安排（注意：剂量需要按你每天 2-3 小时重算） | **每天开工前看** |
| [面试知识树.md](面试知识树.md) | **理论副线**：怎么把项目里的东西讲成面试答案 + 算法刷题路线 | 每完成一级工程后同步补 |
| [知识框架与学习主线.md](知识框架与学习主线.md) | **理论骨架**：800 题反推的 91 个知识模块 | 用它当考卷 |

## 三份「现状与纠正」文档（我补的，不属于计划）

| 文件 | 管什么 |
|---|---|
| [../backend/README.md](../backend/README.md) | 项目怎么跑起来、报错怎么修。**L1 计划里那条硬先决条件（环境能跑）看这份** |
| [01-login-walkthrough.md](01-login-walkthrough.md) | 登录链路的**自测题 + 讲给人听的规则**。配合 L1 的 Day 2/3/4 用，不替代它们 |
| [agent-refactor-plan.md](agent-refactor-plan.md) | 长远的 Agent 工程技术方案。**现在别看**，等 L4–L5 了再回来 |

## 需要知道的三处事实纠正

你现有文档里有几个说法和代码实际情况不符，照做会撞墙：

### 1. 项目没有 Vite 代理

[L1-学习计划.md](L1-学习计划.md) 里两次提到「`vite.config.js` 里的 `/api` 代理把请求转过去」（Day 1 验收标准、Day 4 作业 4）。

**实际情况**：`frontend/vite.config.js` 没有配 `server.proxy`。
[frontend/.env.development](../frontend/.env.development) 里写的是 `VITE_API_BASE_URL=http://127.0.0.1:8000`，前端**直连后端**，靠 [backend/app/main.py:44-55](../backend/app/main.py#L44-L55) 的 CORS 白名单放行。

**影响**：Day 4 作业 4 里「代理绕过了 CORS 吗」这个问题不成立——你的项目是真实的跨域，会真的发 OPTIONS 预检。这其实**更好讲**，因为你能看到一个真实的预检请求。

### 2. `IntegrityError` 的 bug 在另一个文件

[L1-学习计划.md](L1-学习计划.md) Day 1 作业 3 和 Day 2 常见坑里说「`auth_service.py` 第 8 行 `from pymysql import IntegrityError`」。

**实际情况**：[backend/app/services/auth_service.py:8](../backend/app/services/auth_service.py#L8) 导入的是 `sqlalchemy.exc.IntegrityError`，**是正确的**。
真正有问题的是 [backend/app/api/auth.py:2](../backend/app/api/auth.py#L2)：那里导入了 `pymysql.IntegrityError`，而且**完全没被使用**（`auth.py` 里没有任何 `try/except`）。

**影响**：这个 bug 是真实存在的（要修的话是删掉 `auth.py` 第 2 行那个无用导入），但排查位置和计划里写的不一样，别在 `auth_service.py` 里找半天。

### 3. 项目还不是 git 仓库

[L1-学习计划.md](L1-学习计划.md) Day 5 作业 1 要求「把当前未提交的改动拆成 5 个 commit」，[Day 1 作业 1](../docs/L1-学习计划.md) 第 1 步也要求 `git commit` 一次。

**实际情况**：项目根目录下没有 `.git`，**还没初始化仓库**。

**影响**：Day 1 作业 1 的第 1 步会直接失败。开工前先执行 `git init`，并且在第一次 commit **之前**确认 `backend/.gitignore` 已经排除了 `.env`（这个我已经补上了）。

## 关于剂量

[L1-学习计划.md](L1-学习计划.md) 是按**每天 8 小时**设计的（8 天 = 64 小时）。
如果你每天只能投 2-3 小时，实际需要 **3-4 周**才能走完 L1，而不是 8 天。

建议：不要改计划内容，**只改节奏**。把「Day 1」当成「阶段 1」，做 3 个 2-3 小时的时段，做完再进下一个阶段。
文档里 [附 B「如果时间被砍，这样砍」](L1-学习计划.md) 已经给了优先级排序，可以直接照用。
