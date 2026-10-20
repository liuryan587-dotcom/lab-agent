import logging
import sys
import os
from logging.handlers import TimedRotatingFileHandler


def setup_logging():

    # 1. 定义日志格式：时间 | 级别 | logger名字 | 消息
    # 使用 %(asctime)s 等占位符
    log_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    formatter = logging.Formatter(log_format)

    # 2. 创建控制台处理器 StreamHandler
    # 明确指定输出到 sys.stdout，兼容性好
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # 创建文件 handler (保留文件日志)
    os.makedirs("logs", exist_ok=True)
    file_handler = TimedRotatingFileHandler(
        "logs/app.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    # 3. 先清空 root logger 已有的 handler
    logging.root.handlers = []

    # 4. 将我们的 handler 挂载到 root logger
    logging.root.addHandler(console_handler)
    logging.root.addHandler(file_handler)

    # 5. 设置 root logger 的默认级别（建议设为 INFO）
    logging.root.setLevel(logging.INFO)

    # 6. (可选但推荐) 降低 uvicorn 默认 access 日志的级别，避免刷屏
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
