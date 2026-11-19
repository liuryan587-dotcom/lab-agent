"""pytest 的全局配置入口。

这个文件在所有测试模块之前被加载，因此必须在这里完成环境准备：
测试模块顶部的 os.environ.setdefault(...) 会因为"谁先 import 谁赢"互相覆盖。
"""

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 硬赋值，不用 setdefault：测试必须确定，不能依赖外部环境或 import 顺序
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["LLM_API_KEY"] = "test-key"
os.environ["LLM_BASE_URL"] = "http://localhost:11434/v1"
os.environ["LLM_MODEL"] = "test-model"
