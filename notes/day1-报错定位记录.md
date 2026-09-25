# Day 1 作业记录：环境、启动、报错定位

> 填这份文件的过程就是 Day 1 的学习过程。**不要先看答案，先自己填，填不出来再回头查。**
> 完成后这个文件就是 L1 晋级清单第 6 项（"故意改错 DATABASE_URL，能从报错定位到文件"）的证据。

---

## 一、环境快照（先填，这是后面所有排查的基线）

| 项 | 命令 | 我机器上的实际值 |
| --- | --- | --- |
| Python 版本 | `uv run python --version` | |
| 这个 python 是谁 | `uv run python -c "import sys; print(sys.executable)"` | |
| 不带 uv 时 python 是谁 | （**新开一个终端，不在 backend 目录**）`python -c "import sys; print(sys.executable)"` | |
| 后端实际用的 SQLAlchemy | `uv run python -c "import sqlalchemy; print(sqlalchemy.__version__, sqlalchemy.__file__)"` | |
| MySQL 端口 | 看 `backend/.env` 的 DATABASE_URL | |
| 前端 Node 版本 | `node -v` | |

**必须答出来的两个问题：**

1. 上面第二行和第三行的路径**一样吗**？如果不一样，说明什么？
   > 我的答案：

2. 为什么 `backend/.gitignore` 里要写 `.venv`？如果 `.venv` 进了 git 会怎样？
   > 我的答案：

---

## 二、进程与端口图（自己画，画完对照）

要求：画出 **MySQL / 后端 / 前端** 三个进程，标出端口、以及箭头方向上的协议。

```
（在这里画）

例：
浏览器 (你的电脑)
   │  HTTP 请求  http://localhost:5173/api/auth/login
   ▼
Vite dev server  (Node 进程)   端口 ????
   │  代理转发  /api  →  ????
   ▼
uvicorn  (Python 进程)         端口 ????
   │  SQLAlchemy → pymysql → TCP
   ▼
MySQL  (独立进程/服务)          端口 ????
```

**必须答出来的三个问题：**

1. `frontend/vite.config.js` 里代理了哪两个路径？分别转发到哪？
   > 我的答案：

2. 浏览器地址栏里的 `5173` 和请求真正到达的 `8000` 是**同一个请求**吗？中间谁做了转换？
   > 我的答案：

3. 把 `.env` 里的 `DATABASE_URL` 改了，**要不要重启后端**才生效？为什么？
   （提示：看 `backend/app/config.py` 第 19 行 `settings = Settings()` 在什么时机执行）
   > 我的答案：

---

## 三、启动记录

| 步骤 | 命令 | 结果（成功/报错） | 报错的话，第一行是什么 |
| --- | --- | --- | --- |
| 1. MySQL 起来了吗 | 用客户端连一下 | | |
| 2. 启动后端 | `uv run uvicorn app.main:app --reload` | | |
| 3. 打开 `/docs` | 浏览器访问 `http://127.0.0.1:8000/docs` | | |
| 4. 访问根路由 | `/` 返回什么？ | | |
| 5. 启动前端 | `npm run dev` | | |
| 6. 登录 | 浏览器操作 | | |

---

## 四、报错定位训练（Day 1 的核心）

**规则：每改坏一次，都要先把整段报错栈抄下来，标出下面三样，然后才能改回来。**

### 实验 A：ModuleNotFoundError（理解 venv）

做了什么：
```
（写下你执行的命令）
```

完整报错栈（**一字不改地抄，包含最底部的错误行**）：
```
（贴在这里）
```

| 要标出的东西 | 我的答案 |
| --- | --- |
| 最底部的错误类型 + 消息 | |
| 报错发生在**项目里**的哪个文件哪一行 | |
| 这个错误是"环境问题"还是"代码问题" | |
| 怎么修的 | |

---

### 实验 B：数据库连不上（L1 清单项）

做了什么：把 `.env` 里 `DATABASE_URL` 的端口从 `3306` 改成 `3307`，重启后端，发一次登录请求。

完整报错栈：
```
（贴在这里）
```

| 要标出的东西 | 我的答案 |
| --- | --- |
| 最底部的错误类型 + 消息 | |
| 报错发生在项目里的哪个文件哪一行 | |
| 报错链的**中间有一层**是 `app/database.py` 的哪一行？ | |
| 从哪一行可以看出"是数据库连不上"而不是"代码写错了" | |
| **如果 `.env` 里 `DATABASE_URL` 这一行整个删掉**，报错会变成什么？（做一次，记录） | |

> 附加问题：为什么删掉 `DATABASE_URL` 报的是 `ValidationError` 而不是 `OperationalError`？
> （提示：看 `backend/app/config.py` 第 8 行 `DATABASE_URL: str` 有没有默认值）
> 我的答案：

---

### 实验 C：故意在导入时写错名字

做了什么：把 `backend/app/main.py` 第 3 行
`from app.config import UPLOAD_DIR` 改成 `from app.config import UPLOAD_DIRR`

完整报错栈：
```
（贴在这里）
```

| 要标出的东西 | 我的答案 |
| --- | --- |
| 最底部的错误类型 + 消息 | |
| 错误是**哪一行**触发的？是 `import` 那一行，还是别的行？ | |
| 为什么这个错误在"服务启动时"就爆了，而不是"请求进来时"才爆？ | |

---

## 五、错误类型速查（自己总结，别抄答案）

填完上面三个实验，总结一下：**看到什么错误类型，第一反应应该去哪里看？**

| 错误类型 | 大概率是什么问题 | 第一步看哪里 |
| --- | --- | --- |
| `ModuleNotFoundError` | | |
| `ValidationError`（pydantic_settings） | | |
| `OperationalError`（pymysql） | | |
| `AttributeError: 'NoneType'` | | |
| `IntegrityError` | | |
| `RecursionError` | | |

---

## 六、IntegrityError 目击记录（为 L2 埋伏笔）

执行：
```powershell
uv run python -c "import sqlalchemy.exc as s, pymysql as p; print('sqlalchemy:', s.IntegrityError); print('pymysql   :', p.IntegrityError); print('pymysql 是 sqlalchemy 的父类吗:', issubclass(p.IntegrityError, s.IntegrityError))"
```

输出：
```
（贴在这里）
```

**结论（必须自己写一句）：**
> 我的结论：

**再想一步：** `backend/app/services/auth_service.py` 第 8 行 `from pymysql import IntegrityError`，
第 42 行 `except IntegrityError:` —— 那么 SQLAlchemy 在"用户名重复"时抛出的那个异常，能被这个 `except` 抓到吗？
> 我的答案：

**顺手发现（不改，只记录）：** `backend/app/api/auth.py` 第 2 行也 import 了 `IntegrityError`，但那个文件里有 `except` 吗？
> 我的答案：

---

## 七、收尾：3 分钟口述（写完这段才算练完）

合上所有资料，对着空气讲一遍，讲完再回来把这段话写下来：

> "这个项目跑起来需要 ___ 个进程，分别在 ___ 端口。前端发出的 `/api/xxx` 请求，先到 ___，再被 ___ 转发到 ___。
> 如果在项目里改坏了配置，我会先看报错的 ___，找到 ___，因为 ___。"

**卡壳的地方（记下来，明天重讲）：**
1.
2.
