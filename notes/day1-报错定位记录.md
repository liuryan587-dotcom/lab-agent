# Day 1 作业记录：环境、启动、报错定位

> 填这份文件的过程就是 Day 1 的学习过程。**不要先看答案，先自己填，填不出来再回头查。**
> 完成后这个文件就是 L1 晋级清单第 6 项（"故意改错 DATABASE_URL，能从报错定位到文件"）的证据。

---

## 一、环境快照（先填，这是后面所有排查的基线）

| 项                      | 命令                                                                                       | 我机器上的实际值                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| Python 版本             | `uv run python --version`                                                                  | 3.13.5                                                                                                 |
| 这个 python 是谁        | `uv run python -c "import sys; print(sys.executable)"`                                     | D:\workspace\python_project\lab-agent\backend\.venv\Scripts\python.exe                                 |
| 不带 uv 时 python 是谁  | （**新开一个终端，不在 backend 目录**）`python -c "import sys; print(sys.executable)"`     | D:\workspace\anaconda3\python.exe                                                                      |
| 后端实际用的 SQLAlchemy | `uv run python -c "import sqlalchemy; print(sqlalchemy.__version__, sqlalchemy.__file__)"` | 2.0.41 D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\_\_init\_\_.py |
| MySQL 端口              | 看 `backend/.env` 的 DATABASE_URL                                                          | DATABASE_URL=mysql+pymysql://root:123456@127.0.0.1:3306/lab_agent                                      |
| 前端 Node 版本          | `node -v`                                                                                  | v22.19.0                                                                                               |

**必须答出来的两个问题：**

1. 上面第二行和第三行的路径**一样吗**？如果不一样，说明什么？

   > 我的答案：不一样，说明系统中存在多个python解释器。我的全局python由anacoda掌控，而我的具体项目的python由uv掌控。因为不同的项目所需的python版本和依赖不同，若只用全局python环境，容易造成混乱和冲突。所以为每个项目单独生成一个虚拟环境单独进行配置，互不干扰，又方便在其他电脑上复现。
   >
   > **✅ 已修正 · 补充一个关键点（有证据支撑）**：
   > 表格里藏着一条证据——`uv run python` 指向 `.venv\Scripts\python.exe`，不带 uv 时指向 `anaconda3\python.exe`，
   > **而实验 B 的报错栈里，`socket.py`、`asyncio/`、`multiprocessing/` 全部来自 `D:\workspace\anaconda3\Lib\`**。
   > 三条并排看，说明：**venv 里那个 `python.exe` 本身是从 Anaconda 复制出来的；venv 隔离的只有「第三方包」(site-packages)，标准库仍然用 Anaconda 的。**
   > 一句话：**venv 不是"另一个 Python"，而是"另一个包仓库"。**

2. 为什么 `backend/.gitignore` 里要写 `.venv`？如果 `.venv` 进了 git 会怎样？
   > 我的答案：.venv里是单独隔离出的大量的第三方库，如果进了git就会造成项目环境依赖的的混乱，且又占用内存。所以不让它进入git，每个人的电脑上重新生成一份就可以了。
   >
   > **✅ 已修正 · 两处措辞要精确**：
   > | 我原来写的 | 精确说法 |
   > | --- | --- |
   > | "占用内存" | 是**磁盘**（几百 MB 的文件体积），不是运行时内存 |
   > | "造成环境依赖的混乱" | 更准确：**依赖树无法复现**。A 电脑装出 anyio 4.2，B 同事装出 4.9，代码没改却报错 |
   >
   > **三者是一条链**：`pyproject.toml`（我声明的意向）→ `uv.lock`（解算后锁定的整棵依赖树 + 哈希）→ `.venv`（照着 lock 装出来的产物）。
   > 所以"每个人重新生成一份"能生成出**一模一样**的环境，靠的正是 `uv.lock` 这个中间层。

---

## 二、进程与端口图（自己画，画完对照）

要求：画出 **MySQL / 后端 / 前端** 三个进程，标出端口、以及箭头方向上的协议。

```
                        浏览器（页面来源 http://localhost:5173）
                          │
                          │  axios 读 baseURL = http://127.0.0.1:8000
                          │  请求 POST http://127.0.0.1:8000/api/auth/login
                          │  ↑ 带 Origin: http://localhost:5173 → 这是跨域！
                          │
   Vite dev server ───────┘  （5173，只负责把页面发给浏览器，不再转发 API）
   （Node 进程）5173
                          │  HTTP 请求
                          ▼
                    uvicorn（Python 进程）端口 8000
                          │  SQLAlchemy → pymysql → TCP
                          ▼
                    MySQL（独立服务进程）端口 3306
```

**✅ 已修正 · 原图漏了两样东西**：
1. **漏了 Vite 进程（5173）**。它仍然存在，只是职责变了——从"转发 API 的中间人"退回成"只发页面给浏览器"。
2. **没标出"跨域"**。删掉 proxy + 设 `VITE_API_BASE_URL` 之后，请求从 5173 的页面直接打到 8000，**源不同了，这就是跨域**。现在能跑通，是靠 `main.py` 的 CORS 白名单在兜底。

> 对比一下：**如果配了 Vite proxy**，浏览器看到的仍然是 `http://localhost:5173/api/...`（同源），由 Vite 在服务器侧转发到 8000——那样**根本不触发 CORS**。
> 所以"删 proxy 直连"这件事，等于亲手把跨域问题引出来了。这不是坏事，你因此提前摸到了 Day 4 的 CORS。

**必须答出来的三个问题：**

1. `frontend/vite.config.js` 里代理了哪两个路径？分别转发到哪？

   > 我的答案：目前我的vite.config.js并未代理路径，现在是前端直连后端。
   >
   > **✅ 已修正 · 这个答案是对的**（我上一轮基于旧版 `vite.config.js` 给了错误预期，特此更正）。
   > 但要理解：**"没有代理"和"能直连"是两个配置共同作用的结果，缺一不可**：
   > | 配置 | 位置 | 作用 |
   > | --- | --- | --- |
   > | `server.proxy` 被删除 | `frontend/vite.config.js` | 不再由 Vite 转发 |
   > | `VITE_API_BASE_URL=http://127.0.0.1:8000` | `frontend/.env.development` | 告诉 axios 直接打到 8000 |
   >
   > ⚠️ **只删 proxy、不设这个变量 → 404**（因为 `request.js` 第 7 行没有 `|| ''` 兜底了，baseURL 会是 `undefined`，请求打进 5173 而 Vite 上没有 `/api` 路由）。这个坑见文件末尾《遗留待办》。

2. 浏览器地址栏里的 `5173` 和请求真正到达的 `8000` 是**同一个请求**吗？中间谁做了转换？

   > 我的答案：不是，同一个请求。中间有vite做了转换。
   >
   > **✅ 已修正 · 原答案自相矛盾（"不是，同一个请求"），正确说法是**：
   > **是同一个请求**（不是发了两次），**没有中间人做转换**——浏览器直接向 `127.0.0.1:8000` 发出请求。
   > "5173" 和 "8000" 不是两次请求，而是**页面来源**（5173）和**请求目标**（8000）两个不同的地址。
   > 正因为这两个地址不同，才构成**跨域**，才有 CORS 检查。
   > （如果配了 Vite proxy，那才有转换：浏览器发往 5173，Vite 进程在服务器侧转给 8000，且同源、不触发 CORS。）

3. 把 `.env` 里的 `DATABASE_URL` 改了，**要不要重启后端**才生效？为什么？
   （提示：看 `backend/app/config.py` 第 19 行 `settings = Settings()` 在什么时机执行）
   > 我的答案：需要，因为还未连接上数据库就失败了还没有真正启动后端服务，只是uvicorn主进程还在实际后端服务并未运行。
   >
   > **✅ 已修正 · 这题答成了另一道题**。我答的是"实验 B 里后端为什么崩"，本题问的是"**改了 `.env` 为什么必须重启后端**"。正确回答：
   >
   > > 因为 `config.py` 第 19 行 `settings = Settings()` 是在**模块被导入时**执行的，也就是**后端进程启动的那一刻**。执行完，`settings` 就是一个**已经造好的对象**，值固化在内存里。
   > > `.env` 只是"启动时读一次的文件"，进程活着的时候不会再读它。所以改了 `.env` 必须重启，让模块重新导入、`Settings()` 重新执行一次。
   >
   > （附注：连接失败 → 后端未真正启动 → 只剩 uvicorn 主进程——这段描述本身是**对的**，只是不属于本题。见实验 B 的补充。）

---

## 三、启动记录

| 步骤              | 命令                                    | 结果（成功/报错） | 报错的话，第一行是什么 |
| ----------------- | --------------------------------------- | ----------------- | ---------------------- |
| 1. MySQL 起来了吗 | 用客户端连一下                          | 成功              |                        |
| 2. 启动后端       | `uv run uvicorn app.main:app --reload`  | 成功              |                        |
| 3. 打开 `/docs`   | 浏览器访问 `http://127.0.0.1:8000/docs` | 成功              |                        |
| 4. 访问根路由     | `/` 返回什么？                          | 成功，返回 `{"message":"Hello FastAPI"}` |                        |
| 5. 启动前端       | `npm run dev`                           | 成功              |                        |
| 6. 登录           | 浏览器操作                              | 成功              |                        |

---

## 四、报错定位训练（Day 1 的核心）

**规则：每改坏一次，都要先把整段报错栈抄下来，标出下面三样，然后才能改回来。**

### 实验 A：ModuleNotFoundError（理解 venv）

做了什么：

```
python -c "import cuda; print(cuda.__version__)"
```

完整报错栈（**一字不改地抄，包含最底部的错误行**）：

```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import cuda; print(cuda.__version__)
    ^^^^^^^^^^^
ModuleNotFoundError: No module named 'cuda'
```

| 要标出的东西                         | 我的答案                                    |
| ------------------------------------ | ------------------------------------------- |
| 最底部的错误类型 + 消息              | ModuleNotFoundError: No module named 'cuda' |
| 报错发生在**项目里**的哪个文件哪一行 | **没有项目文件。** `File "<string>", line 1` 里的 `<string>` 表示这是用 `-c` 参数直接执行的代码，不是文件。**这次栈里连一个项目文件都没有——这本身就是信息**：说明错误发生在"程序还没开始跑"的阶段，跟项目代码无关。 |
| 这个错误是"环境问题"还是"代码问题"   | **既不是环境问题，也不是代码问题，是第三种：包名根本不存在。** 而且更关键的是——**我是在哪个 Python 里执行的**（提示符 `(base)` → Anaconda base 环境）。如果拿到 `backend` 里用 `uv run python -c "..."` 跑，报错一模一样，因为 venv 里也没有 `cuda`。 |
| 怎么修的                             | **不需要修**——`cuda` 本来就不是这个项目要用的包，我只是拿它做实验。**"这条报错不需要修"本身就是一个判断**，不是每条红字都要动手。 |

---

### 实验 B：数据库连不上（L1 清单项）

做了什么：把 `.env` 里 `DATABASE_URL` 的端口从 `3306` 改成 `3307`，重启后端，发一次登录请求。

完整报错栈：

```
(backend) D:\workspace\python_project\lab-agent\backend>uvicorn app.main:app --reload
INFO:     Will watch for changes in these directories: ['D:\\workspace\\python_project\\lab-agent\\backend']
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [61812] using StatReload
Process SpawnProcess-1:
Traceback (most recent call last):
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\pymysql\connections.py", line 649, in connect
    sock = socket.create_connection(
        (self.host, self.port), self.connect_timeout, **kwargs
    )
  File "D:\workspace\anaconda3\Lib\socket.py", line 864, in create_connection
    raise exceptions[0]
  File "D:\workspace\anaconda3\Lib\socket.py", line 849, in create_connection
    sock.connect(sa)
    ~~~~~~~~~~~~^^^^
ConnectionRefusedError: [WinError 10061] 由于目标计算机积极拒绝，无法连接。

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 145, in __init__
    self._dbapi_connection = engine.raw_connection()
                             ~~~~~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 3297, in raw_connection
    return self.pool.connect()
           ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 449, in connect
    return _ConnectionFairy._checkout(self)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 1264, in _checkout
    fairy = _ConnectionRecord.checkout(pool)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 713, in checkout
    rec = pool._do_get()
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\impl.py", line 179, in _do_get
    with util.safe_reraise():
         ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\util\langhelpers.py", line 224, in __exit__
    raise exc_value.with_traceback(exc_tb)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\impl.py", line 177, in _do_get
    return self._create_connection()
           ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 390, in _create_connection
    return _ConnectionRecord(self)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 675, in __init__
    self.__connect()
    ~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 901, in __connect
    with util.safe_reraise():
         ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\util\langhelpers.py", line 224, in __exit__
    raise exc_value.with_traceback(exc_tb)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 897, in __connect
    self.dbapi_connection = connection = pool._invoke_creator(self)
                                         ~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\create.py", line 646, in connect
    return dialect.connect(*cargs, **cparams)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\default.py", line 625, in connect
    return self.loaded_dbapi.connect(*cargs, **cparams)  # type: ignore[no-any-return]  # NOQA: E501
           ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\pymysql\connections.py", line 361, in __init__
    self.connect()
    ~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\pymysql\connections.py", line 716, in connect
    raise exc
pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on '127.0.0.1' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)")

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "D:\workspace\anaconda3\Lib\multiprocessing\process.py", line 313, in _bootstrap
    self.run()
    ~~~~~~~~^^
  File "D:\workspace\anaconda3\Lib\multiprocessing\process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\_subprocess.py", line 80, in subprocess_started
    target(sockets=sockets)
    ~~~~~~^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 66, in run
    return asyncio.run(self.serve(sockets=sockets))
           ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\base_events.py", line 725, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 70, in serve
    await self._serve(sockets)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 77, in _serve
    config.load()
    ~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\config.py", line 435, in load
    self.loaded_app = import_from_string(self.app)
                      ~~~~~~~~~~~~~~~~~~^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\importer.py", line 19, in import_from_string
    module = importlib.import_module(module_str)
  File "D:\workspace\anaconda3\Lib\importlib\__init__.py", line 88, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1026, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "D:\workspace\python_project\lab-agent\backend\app\main.py", line 19, in <module>
    Base.metadata.create_all(bind=engine)
    ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\sql\schema.py", line 5924, in create_all
    bind._run_ddl_visitor(
    ~~~~~~~~~~~~~~~~~~~~~^
        ddl.SchemaGenerator, self, checkfirst=checkfirst, tables=tables
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 3247, in _run_ddl_visitor
    with self.begin() as conn:
         ~~~~~~~~~~^^
  File "D:\workspace\anaconda3\Lib\contextlib.py", line 141, in __enter__
    return next(self.gen)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 3237, in begin
    with self.connect() as conn:
         ~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 3273, in connect
    return self._connection_cls(self)
           ~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 147, in __init__
    Connection._handle_dbapi_exception_noconnection(
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^
        err, dialect, engine
        ^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 2436, in _handle_dbapi_exception_noconnection
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 145, in __init__
    self._dbapi_connection = engine.raw_connection()
                             ~~~~~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\base.py", line 3297, in raw_connection
    return self.pool.connect()
           ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 449, in connect
    return _ConnectionFairy._checkout(self)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 1264, in _checkout
    fairy = _ConnectionRecord.checkout(pool)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 713, in checkout
    rec = pool._do_get()
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\impl.py", line 179, in _do_get
    with util.safe_reraise():
         ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\util\langhelpers.py", line 224, in __exit__
    raise exc_value.with_traceback(exc_tb)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\impl.py", line 177, in _do_get
    return self._create_connection()
           ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 390, in _create_connection
    return _ConnectionRecord(self)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 675, in __init__
    self.__connect()
    ~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 901, in __connect
    with util.safe_reraise():
         ~~~~~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\util\langhelpers.py", line 224, in __exit__
    raise exc_value.with_traceback(exc_tb)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\pool\base.py", line 897, in __connect
    self.dbapi_connection = connection = pool._invoke_creator(self)
                                         ~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\create.py", line 646, in connect
    return dialect.connect(*cargs, **cparams)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\sqlalchemy\engine\default.py", line 625, in connect
    return self.loaded_dbapi.connect(*cargs, **cparams)  # type: ignore[no-any-return]  # NOQA: E501
           ~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\pymysql\connections.py", line 361, in __init__
    self.connect()
    ~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\pymysql\connections.py", line 716, in connect
    raise exc
sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError) (2003, "Can't connect to MySQL server on '127.0.0.1' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)")
(Background on this error at: https://sqlalche.me/e/20/e3q8)

```

| 要标出的东西            | 我的答案                                                                                                                                                                     |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 最底部的错误类型 + 消息 | sqlalchemy.exc.OperationalError: (pymysql.err.OperationalError) (2003, "Can't connect to MySQL server on '127.0.0.1' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)") |
| 报错发生在项目里的哪个文件哪一行 | `main.py:19 Base.metadata.create_all(bind=engine)` —— 这是**唯一属于本项目的帧**，再往上没有我的文件了。（`main.py:5` 只负责 import，没进栈；往下全是 `site-packages`，即"路过的第三方库"） |
| 报错链的**中间有一层**是 `app/database.py` 的哪一行？ | **没有这一层**（我的观察是对的——但原因比题目预想的更值得说，见下方"因果修正"） |
| 从哪一行可以看出"是数据库连不上"而不是"代码写错了" | pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on '127.0.0.1' ([WinError 10061] 由于目标计算机积极拒绝，无法连接。)") |
| **如果 `.env` 里 `DATABASE_URL` 这一行整个删掉**，报错会变成什么？（做一次，记录） | ValidationError: DATABASE_URL Field required |
| **如果密码写错**（`root:123456` → `root:654321`），报错会变成什么？（**待补做**） | *(预期是 `OperationalError (1045, "Access denied for user 'root'@'localhost'")`)* |

**我原本写的推理过程**（保留作对照）：

> 报错链经过的文件很多，其中我写的文件第一个出现的是 `main.py:19 Base.metadata.create_all(bind=engine)`，再往上也没有我的文件了。
> 到 main.py 第 19 行时，我往上跳转找到 engine 的出处在 database.py 中的这一句：`engine = create_engine(settings.DATABASE_URL)`。
> 推断应该是传入的 settings.DATABASE_URL 出错了，进而找到 .env 文件发现 DATABASE_URL 的值的问题。

**✅ 已修正 · 因果要说准**（方向对，但措辞会误导自己）：

- ❌ `DATABASE_URL` **本身没写错**（格式、用户名、库名全对）
- ✅ 是它**指向的端口上没有服务在监听**——我把它从 3306 改成了 3307，MySQL 只在 3306 上听

准确说法是：**"我让它去了一个错误的地方"，而不是"值写错了格式"。** 这个区分决定了排查方向。

**✅ 已修正 · 补上"为什么 `database.py` 不在报错栈里"的完整推理**（本次作业含金量最高的一处）：

题目原来的问法有误导性。正确答案是：**`database.py` 确实不在栈里，但不是因为我没找到，而是因为它根本不可能在里面。**

时间线如下：

```text
① uvicorn 导入 app.main
        ↓
② main.py 第 5 行：from app.database import Base, engine
        ↓
③ database.py 第 6 行执行：engine = create_engine(settings.DATABASE_URL)
        ↓   ← 关键！create_engine() 【不会连接数据库】，只是造一个"连接工厂"对象
        ↓     （所以它执行成功了，没有任何报错）
④ main.py 第 19 行：Base.metadata.create_all(bind=engine)
        ↓   ← 到这一步才真正去连数据库！所以报错栈里出现的是 main.py:19
```

**`database.py` 是"定义问题的地方"，`main.py:19` 是"问题爆发的地方"。这两者可以不在同一个文件里。**

> 一句话记住：**`create_engine()` 是"写地址"，`create_all()` 才是"出门寄信"。地址写错了不会当场报错，出去寄的时候才发现。**

> 附加问题：为什么删掉 `DATABASE_URL` 报的是 `ValidationError` 而不是 `OperationalError`？
> （提示：看 `backend/app/config.py` 第 8 行 `DATABASE_URL: str` 有没有默认值）
> 我的答案：因为在启动后端服务时，会先校验配置参数当DATABASE_URL为空而又没有默认值时，就会报错，此时并未开始与数据库进行连接。

**✅ 已修正 · 三种"改坏"方式的对比表（补做"密码写错"这一行后就完整了）**：

| 改坏什么 | 报出的错误 | 失败在哪个阶段 | TCP 请求发出去了吗 |
| --- | --- | --- | --- |
| 端口改成 3307 | `OperationalError (2003)` Can't connect | **连接建立** | 发了，被拒绝（端口上没人监听） |
| 整行删掉 | `ValidationError: Field required` | **配置校验（Pydantic）** | **根本没发** |
| 密码写错 *(待补做)* | `OperationalError (1045)` Access denied | **服务器认证** | 发了，也连上了，但密码不对 |

> 这三层对应三个完全不同的排查方向：**查配置 → 查网络/服务 → 查凭据**。
> 能把它们分开说清楚，面试里回答"怎么排查数据库连不上"就不会只剩一句"连不上"。

---

### 实验 C：故意在导入时写错名字

做了什么：把 `backend/app/main.py` 第 3 行
`from app.config import UPLOAD_DIR` 改成 `from app.config import UPLOAD_DIRR`

完整报错栈：

```
Process SpawnProcess-1:
Traceback (most recent call last):
  File "D:\workspace\anaconda3\Lib\multiprocessing\process.py", line 313, in _bootstrap
    self.run()
    ~~~~~~~~^^
  File "D:\workspace\anaconda3\Lib\multiprocessing\process.py", line 108, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\_subprocess.py", line 80, in subprocess_started
    target(sockets=sockets)
    ~~~~~~^^^^^^^^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 66, in run
    return asyncio.run(self.serve(sockets=sockets))
           ~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\runners.py", line 195, in run
    return runner.run(main)
           ~~~~~~~~~~^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\runners.py", line 118, in run
    return self._loop.run_until_complete(task)
           ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^
  File "D:\workspace\anaconda3\Lib\asyncio\base_events.py", line 725, in run_until_complete
    return future.result()
           ~~~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 70, in serve
    await self._serve(sockets)
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\server.py", line 77, in _serve
    config.load()
    ~~~~~~~~~~~^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\config.py", line 435, in load
    self.loaded_app = import_from_string(self.app)
                      ~~~~~~~~~~~~~~~~~~^^^^^^^^^^
  File "D:\workspace\python_project\lab-agent\backend\.venv\Lib\site-packages\uvicorn\importer.py", line 19, in import_from_string
    module = importlib.import_module(module_str)
  File "D:\workspace\anaconda3\Lib\importlib\__init__.py", line 88, in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  File "<frozen importlib._bootstrap_external>", line 1026, in exec_module
  File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  File "D:\workspace\python_project\lab-agent\backend\app\main.py", line 3, in <module>
    from app.config import UPLOAD_DIRRR
ImportError: cannot import name 'UPLOAD_DIRRR' from 'app.config' (D:\workspace\python_project\lab-agent\backend\app\config.py)
```

| 要标出的东西                                                 | 我的答案                                                                                                                       |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| 最底部的错误类型 + 消息                                      | ImportError: cannot import name 'UPLOAD_DIRRR' from 'app.config' (D:\workspace\python_project\lab-agent\backend\app\config.py) |
| 错误是**哪一行**触发的？是 `import` 那一行，还是别的行？     | import那一行                                                                                                                   |
| 为什么这个错误在"服务启动时"就爆了，而不是"请求进来时"才爆？ | 服务启动时会先进性app.main中的模块导入，然后建立数据库连接 。直到创建FastApi对象才开始请求。                                   |

---

## 五、错误类型速查（自己总结，别抄答案）

填完上面三个实验，总结一下：**看到什么错误类型，第一反应应该去哪里看？**

| 错误类型                               | 大概率是什么问题 | 第一步看哪里               |
| -------------------------------------- | ---------------- | -------------------------- |
| `ModuleNotFoundError`                  | **三种可能**：① 包真没装 ② 装在了**另一个 Python 环境**里 ③ **名字拼错了** | ① 先确认我在用哪个 Python（`sys.executable`）② 再确认包名拼写。**实验 A 恰好是第 ③ 种**（`cuda` 根本不存在），所以不能一律归为"包没装" |
| `ValidationError`（pydantic_settings） | 配置问题         | .env或config.py            |
| `OperationalError`（pymysql）          | mysql的连接问题  | .env 的 DATABASE_URL       |
| `AttributeError: 'NoneType'`           | 属性为空         | 代码里去属性的那里         |
| `IntegrityError`                       | 违反数据库约束   | 具体操作的那张表           |
| `RecursionError`                       | 无限递归         | 最后一次重复出现的那个函数 |

---

## 六、IntegrityError 目击记录（为 L2 埋伏笔）

执行：

```powershell
uv run python -c "import sqlalchemy.exc as s, pymysql as p; print('sqlalchemy:', s.IntegrityError); print('pymysql   :', p.IntegrityError); print('pymysql 是 sqlalchemy 的父类吗:', issubclass(p.IntegrityError, s.IntegrityError))"
```

输出：

```
sqlalchemy: <class 'sqlalchemy.exc.IntegrityError'>
pymysql   : <class 'pymysql.err.IntegrityError'>
pymysql 是 sqlalchemy 的父类吗: False
```

**结论（必须自己写一句）：**

> 我的结论：这两个类并无关系，其IntegrituError也是不同的。

**✅ 已修正 · 补上"后果"，这样才闭环**：

> SQLAlchemy 在**用户名重复**时抛的是 `sqlalchemy.exc.IntegrityError`
> → `auth_service.py:42` 的 `except IntegrityError:`（抓的是 `pymysql.err.IntegrityError`）**抓不到**
> → 异常继续向上冒，被 `main.py:44` 注册的 `global_exception_handler` 兜住
> → 返回 **500「服务器内部错误」**
>
> **也就是说：并发注册同名账号时，用户看到的是 500，而不是"账号已存在"。**
> 这就是一个真实 Bug 的完整因果链 —— L2 的第一件事就是修它。

**再想一步：** `backend/app/services/auth_service.py` 第 8 行 `from pymysql import IntegrityError`，
第 42 行 `except IntegrityError:` —— 那么 SQLAlchemy 在"用户名重复"时抛出的那个异常，能被这个 `except` 抓到吗？

> 我的答案：不能，因为这两个异常只是同名本质并不一样

**顺手发现（不改，只记录）：** `backend/app/api/auth.py` 第 2 行也 import 了 `IntegrityError`，但那个文件里有 `except` 吗？

> 我的答案：没有

---

### 七之前 · 待办决定：JWT_SECRET_KEY 暂不轮换

**✅ 已修正 · 把"暂不轮换"写成一条有理由、有后续动作的待办，而不是含糊跳过**：

> **决定：暂不轮换 `JWT_SECRET_KEY`。**
>
> 理由：
> 1. 这是**本地个人仓库**，`.env` 已通过 `git rm --cached` 移出索引，**不再新增泄露**；
> 2. 密钥**仍存在于历史提交里**。若将来把仓库 push 到 GitHub（或分享给任何人），**必须在那之前轮换**；
> 3. 现在不轮换是因为**还没理解轮换的影响面** —— 等 Day 3 读懂 `utils/jwt.py`（签发）和 `dependencies/auth.py`（校验）之后，我会明白"改了这个 key，为什么所有旧 token 立刻失效"，那时再动手。
>
> **触发条件（写清楚，别忘）**：准备 push 到远程 / 分享仓库 / 部署到服务器 —— 三件事任一发生，先轮换再推。

---

## 七、收尾：3 分钟口述（写完这段才算练完）

合上所有资料，对着空气讲一遍，讲完再回来把这段话写下来：

> **我原来写的（保留作对照，见下方"我错在哪"）：**
>
> > "这个项目跑起来需要 *** 3个进程，分别在 ***前端5173，后端8000和数据库3306 端口。前端发出的 `/api/login` 请求，先到 ***api/auth.js，再被 ***vite.config.js 转发到 **_http://127.0.0.1:8000/app/api/login。
> > 如果在项目里改坏了配置，我会先看报错的 _**底部，找到 ***报错信息，因为 ***报错信息会在底部输出，从下往上看找到自己项目的文件出错的地方。"

**✅ 已修正 · 修正后的完整版（照着讲一遍，讲顺了才算过）：**

> "这个项目跑起来需要 **3 个进程**：Vite 开发服务器在 **5173**（负责把页面发给浏览器）、uvicorn 在 **8000**（跑 FastAPI）、MySQL 在 **3306**。
>
> 点登录时，浏览器里的 axios 实例读了 `VITE_API_BASE_URL=http://127.0.0.1:8000`，往 **`POST http://127.0.0.1:8000/api/auth/login`** 发一个 JSON。这个路径是**两段路由前缀拼出来的**：`/api` 来自 `api/__init__.py`，`/auth` 来自 `api/auth.py`。
>
> 因为页面来源是 5173、请求目标是 8000，属于**跨域**，所以浏览器会先发一个 **OPTIONS 预检请求**，靠 `main.py` 里的 CORS 白名单放行。
>
> 请求到了后端：FastAPI 用 `LoginRequest` 校验请求体 → `auth_service.login()` 查 MySQL、用 bcrypt 验密码、签发 JWT → 用统一的 `Response` 包起来返回。
>
> 前端拦截器看到 `code === 200`，把 token 存起来，路由跳到 `/manager/home`。
>
> **如果在项目里改坏了配置，我会先看报错栈的最底部（错误类型和消息），然后从下往上找第一个属于我自己项目的文件 —— 因为上面的第三方库帧都只是路过的。**"

**✅ 已修正 · 我原来那 4 处错误（这是最该复习的部分）：**

| # | 我原来写的 | 正确 | 为什么错 |
| --- | --- | --- | --- |
| 1 | `/api/login` | **`/api/auth/login`** | 两段 prefix 拼起来：`APIRouter(prefix="/api")`（`api/__init__.py:6`）+ `APIRouter(prefix="/auth")`（`api/auth.py:12`）。**前缀是拼出来的，不是写死的** |
| 2 | "先到 `api/auth.js`" | `api/auth.js` 是 **axios 的封装层（发起点）**，不是网络目的地 | 请求不会"到"一个 `.js` 文件。它的作用是"用哪个 URL + 哪个方法去请求" |
| 3 | "被 `vite.config.js` 转发" | 顺序错了，而且现在是**直连，没有转发** | `vite.config.js` 是**配置文件**（`npm run dev` 时读一次），**不是转发者**。真要转发，转发者是 **Vite dev server 进程**，且现在这个 proxy 已被删除 |
| 4 | `.../app/api/login` | 去掉 `app`、加上 `auth` | **`app` 是 Python 包目录名，不会出现在 URL 里。** URL 里的 `/api` 来自路由前缀，跟文件夹名是两回事 |

**卡壳的地方（记下来，明天重讲）：**

1. ⚠️ **待填** —— 必须真的合上资料讲一遍再写。第一次讲时，"没有中间人做转换"和"5173 是页面来源、8000 是请求目标"这两句话最容易说不顺。
2. ⚠️ **待填**
3. ⚠️ **待填**

---

## 附：遗留待办（Day 1 结束后要处理的）

| # | 事项 | 为什么 | 优先级 |
| --- | --- | --- | --- |
| 1 | **`frontend/.env.development` 的 git 版本是空的**，但代码现在依赖它。要么把值提交上去，要么给 `request.js` 加回 `\|\| ''` 兜底并恢复 proxy | 别人 clone 下来前端会 404 | 🔴 高 |
| 2 | 补做"密码写错"的报错，凑齐三阶段对比表 | 三层排查方向是面试点 | 🟡 中 |
| 3 | 做一次 CORS 实验：临时删掉 `main.py` 里 `origins` 的 `http://127.0.0.1:5173` → 看 Console 红字和 Network 里 `(failed)` → 还原 | 亲眼看到"CORS 是浏览器行为，后端根本没被调用" | 🟡 中 |
| 4 | 若将来 push 到远程：**先轮换 `JWT_SECRET_KEY`** | 历史提交里仍有旧密钥 | 🔴 触发即做 |
