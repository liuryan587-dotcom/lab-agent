#!/usr/bin/env python
"""分块策略对照实验（离线，不写库、不改数据）。

目的：回答面试里那个问题——「你说这样切合适，验证过吗？」

做法：同一份文档，三种切法，同一批问题，比 Recall@1 / Recall@3：

    A 整篇一块（当前项目的做法，文档小的时候够用）
    B 按 markdown 标题切（无重叠）
    C 固定长度切 + 15% 重叠

依赖本机 Ollama（qwen3-embedding:8b），跑之前先启动：

    ollama serve

跑法（在 backend 目录下）：

    .\\.venv\\Scripts\\python.exe tests\\eval\\chunk_experiment.py docs\\slot-rules.md

题目写在下面的 QUESTIONS 里，换成你自己文档的问题即可。
"""

import json
import pathlib
import sys
import urllib.error
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "qwen3-embedding:8b"

# (问题, 命中判定关键词) —— 关键词出现在检索到的块里就算「能答」
# 直接取自评估集 rag 类的 6 条，对应 backend/data/kb 下的四份文档
QUESTIONS = [
    ("计算机实验室周末几点到几点开放", "09:00-17:00"),
    ("物理实验室每天开到几点", "20:00"),
    ("已经通过的预约本人可以取消吗", "本人可以取消"),
    ("电子显微镜使用前要检查什么", "样品台"),
    ("进实验室要穿什么", "实验服"),
    ("设备损坏了怎么办", "管理员"),
]


def embed(text: str) -> list[float]:
    payload = json.dumps({"model": MODEL, "prompt": text}).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-9)


# ------------------------------------------------------------------ 三种切法
def split_whole(text: str) -> list[str]:
    return [text]


def split_by_heading(text: str) -> list[str]:
    chunks, cur = [], []
    for line in text.splitlines():
        if line.startswith("#") and cur:
            chunks.append("\n".join(cur).strip())
            cur = [line]
        else:
            cur.append(line)
    if cur:
        chunks.append("\n".join(cur).strip())
    return [c for c in chunks if c]


def split_fixed(text: str, size: int = 300, overlap: int = 45) -> list[str]:
    chunks, i = [], 0
    while i < len(text):
        chunks.append(text[i : i + size])
        i += size - overlap
    return [c.strip() for c in chunks if c.strip()]


# ------------------------------------------------------------------ 主流程
def run(name: str, chunks: list[str], qvecs) -> None:
    cvecs = [embed(c) for c in chunks]
    hit1 = hit3 = 0
    rows = []
    for (question, keyword), qv in zip(QUESTIONS, qvecs):
        ranked = sorted(
            zip(chunks, cvecs), key=lambda p: cosine(qv, p[1]), reverse=True
        )
        r1 = keyword in ranked[0][0]
        r3 = any(keyword in c for c, _ in ranked[:3])
        hit1 += r1
        hit3 += r3
        rows.append((question, ranked[0][0][:40].replace("\n", " "), r1, r3))

    n = len(QUESTIONS)
    print(f"\n=== {name}：{len(chunks)} 块，平均 {sum(map(len, chunks)) // len(chunks)} 字")
    for q, top, r1, r3 in rows:
        print(f"  {'✓' if r1 else '✗'} R@1 {'✓' if r3 else '✗'} R@3 | {q} → {top}…")
    print(f"  Recall@1 = {hit1}/{n}   Recall@3 = {hit3}/{n}")


def load_corpus(target: pathlib.Path) -> tuple[str, str]:
    """目录 → 合并成一份「手册」；文件 → 直接读。"""
    if target.is_dir():
        parts = []
        for p in sorted(target.glob("*.md")):
            parts.append(f"# {p.stem}\n\n{p.read_text(encoding='utf-8').strip()}")
        return f"{target}（合并 {len(parts)} 篇）", "\n\n".join(parts)
    return f"{target}", target.read_text(encoding="utf-8")


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else "data/kb"
    target = pathlib.Path(raw)
    if not target.exists():
        target = pathlib.Path(__file__).resolve().parents[2] / raw
    label, text = load_corpus(target)
    print(f"语料：{label}（{len(text)} 字）")

    try:
        qvecs = [embed(q) for q, _ in QUESTIONS]
    except (urllib.error.URLError, ConnectionError) as exc:
        print(f"\n连不上 Ollama（{OLLAMA_URL}）：{exc}")
        print("先启动 Ollama：ollama serve   然后重跑本脚本")
        sys.exit(1)

    run("A 整篇一块", split_whole(text), qvecs)
    run("B 按标题切", split_by_heading(text), qvecs)
    run("C 固定 300 字 + 15% 重叠", split_fixed(text), qvecs)


if __name__ == "__main__":
    main()
