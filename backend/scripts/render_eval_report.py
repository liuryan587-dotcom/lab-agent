"""Render an Agent evaluation JSON file as a self-contained HTML report.

Usage from backend/:
    .venv/Scripts/python.exe scripts/render_eval_report.py tests/eval/results/run.json
    .venv/Scripts/python.exe scripts/render_eval_report.py tests/eval/results/run.json --output ../docs/agent-eval-report.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = BACKEND_ROOT / "tests" / "eval"
CATEGORY_LABELS = {
    "rag": "RAG 检索",
    "tool": "工具选择",
    "write": "业务写入",
    "multi_turn": "多轮上下文",
    "multi_turn_memory": "多轮记忆",
    "safety": "写操作安全",
}
METRIC_LABELS = {
    "tools": "工具选择",
    "args": "工具参数",
    "order": "工具顺序",
    "doc": "知识库命中",
    "answer": "回答断言",
    "db": "数据库状态",
    "turns": "多轮断言",
    "write_blocked": "禁止工具",
}


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def load_questions() -> dict[str, str]:
    try:
        import yaml

        questions = {}
        for name in ("dataset.yaml", "dataset_multi_turn.yaml"):
            cases = yaml.safe_load((EVAL_DIR / name).read_text(encoding="utf-8")) or []
            for case in cases:
                questions[case["id"]] = case.get("question") or "\n".join(
                    turn.get("content", "") for turn in case.get("messages", [])
                    if turn.get("role") == "user"
                ) or "\n".join(case.get("turns", []))
        return questions
    except Exception:
        return {}


def format_ratio(ok, count) -> str:
    if not count or ok is None:
        return "未测"
    return f"{ok}/{count} · {ok / count:.1%}"


def summarize(records: list[dict]) -> dict:
    active = [record for record in records if not record.get("skipped")]
    passed = sum(bool(record.get("passed")) for record in active)
    skipped = len(records) - len(active)
    failed = len(active) - passed

    categories: dict[str, list[dict]] = {}
    for record in records:
        categories.setdefault(record.get("category", "unknown"), []).append(record)

    capabilities = {
        "端到端": [record.get("passed") for record in active],
        "工具选择": [record.get("checks", {}).get("tools") for record in active],
        "工具参数": [record.get("checks", {}).get("args") for record in active],
        "检索命中": [record.get("checks", {}).get("doc") for record in active],
        "回答断言": [record.get("checks", {}).get("answer") for record in active],
        "写操作安全": [
            record.get("checks", {}).get("db")
            for record in active if record.get("category") == "safety"
        ],
        "多轮记忆": [
            record.get("checks", {}).get("turns")
            for record in active
            if record.get("category") == "multi_turn_memory"
        ],
    }
    metrics = {}
    for name, values in capabilities.items():
        measurable = [value for value in values if value is not None]
        metrics[name] = (sum(bool(value) for value in measurable), len(measurable))

    latencies = [record.get("latency_ms", 0) for record in active if record.get("latency_ms")]
    token_totals = [
        (record.get("tokens") or {}).get("prompt", 0)
        + (record.get("tokens") or {}).get("completion", 0)
        for record in active
    ]
    return {
        "total": len(records), "active": len(active), "passed": passed,
        "failed": failed, "skipped": skipped, "categories": categories,
        "metrics": metrics,
        "latency_avg": round(sum(latencies) / len(latencies)) if latencies else None,
        "tokens_avg": round(sum(token_totals) / len(token_totals)) if token_totals else None,
    }


def render_record(record: dict, questions: dict[str, str], index: int) -> str:
    skipped = record.get("skipped", False)
    passed = record.get("passed", False) and not skipped
    status = "跳过" if skipped else "通过" if passed else "失败"
    state_class = "skip" if skipped else "pass" if passed else "fail"
    checks = record.get("checks") or {}
    check_html = []
    for key, value in checks.items():
        if value is None:
            continue
        label = METRIC_LABELS.get(key, key)
        check_html.append(
            f'<span class="check {"ok" if value else "bad"}">{esc(label)}：{"通过" if value else "失败"}</span>'
        )
    if not check_html:
        check_html.append('<span class="check unknown">本结果文件未保存断言明细</span>')

    expect = json.dumps(record.get("expect") or {}, ensure_ascii=False, indent=2)
    tool_calls = record.get("tool_calls")
    if tool_calls is None:
        tools = record.get("tools") or []
        calls_html = "<p class='muted'>本次 JSON 未保存工具参数，只能查看工具名。</p>" if tools else "<p class='muted'>沒有工具调用记录。</p>"
        calls_html += f"<pre>{esc(json.dumps(tools, ensure_ascii=False, indent=2))}</pre>" if tools else ""
    else:
        calls_html = f"<pre>{esc(json.dumps(tool_calls, ensure_ascii=False, indent=2))}</pre>"
    outputs = record.get("tool_outputs")
    outputs_html = (
        f"<pre>{esc(json.dumps(outputs, ensure_ascii=False, indent=2))}</pre>"
        if outputs else "<p class='muted'>没有保存工具输出。</p>"
    )
    turn_tools = record.get("turn_tools")
    turns_html = ""
    if turn_tools is not None:
        turns_html = f"<h4>各轮工具</h4><pre>{esc(json.dumps(turn_tools, ensure_ascii=False, indent=2))}</pre>"
    fails = record.get("fails") or []
    fails_html = "".join(f"<li>{esc(fail)}</li>" for fail in fails) or "<li>无断言失败</li>"
    answer = record.get("answer") or ""
    if not answer and record.get("turn_answers"):
        answer = "\n\n".join(record["turn_answers"])
    question = record.get("question") or questions.get(record.get("id"), "")
    if not question:
        question = "此历史结果未记录原始问题，需结合对应数据集查看。"

    return f"""<details class="sample {state_class}" {'open' if not passed else ''}>
      <summary><span class="sample-id">{index:02d} · {esc(record.get('id'))}</span><span class="category">{esc(CATEGORY_LABELS.get(record.get('category'), record.get('category')))}</span><span class="badge {state_class}">{status}</span><span class="sample-latency">{record.get('latency_ms', 0)} ms</span></summary>
      <div class="sample-body">
        <section><h4>输入问题</h4><p class="preserve">{esc(question)}</p></section>
        <section><h4>断言状态</h4><div class="checks">{''.join(check_html)}</div><h4>失败原因</h4><ul>{fails_html}</ul></section>
        <section><h4>期望</h4><pre>{esc(expect)}</pre></section>
        <section><h4>实际工具调用</h4>{calls_html}{turns_html}</section>
        <section><h4>工具输出</h4>{outputs_html}</section>
        <section><h4>最终回答</h4><p class="preserve">{esc(answer) or '（无回答记录）'}</p></section>
        <section><h4>用量与错误</h4><p>Prompt {((record.get('tokens') or {}).get('prompt', 0))} tokens · Completion {((record.get('tokens') or {}).get('completion', 0))} tokens</p><p class="preserve error">{esc(record.get('error') or '') or '无执行错误'}</p></section>
      </div>
    </details>"""


def build_html(payload: dict, source: Path) -> str:
    meta = payload.get("meta") or {}
    stored_summary = payload.get("summary") or {}
    summary = summarize(payload.get("records") or [])
    questions = load_questions()
    category_rows = []
    for category, items in summary["categories"].items():
        active = [item for item in items if not item.get("skipped")]
        ok = sum(bool(item.get("passed")) for item in active)
        skipped = len(items) - len(active)
        failed = len(active) - ok
        category_rows.append(
            f"<tr><td>{esc(CATEGORY_LABELS.get(category, category))}</td><td>{ok}/{len(active)} ({ok / len(active):.1%})</td><td>{failed}</td><td>{skipped}</td><td>{len(items)}</td></tr>"
            if active else
            f"<tr><td>{esc(CATEGORY_LABELS.get(category, category))}</td><td>未测</td><td>0</td><td>{skipped}</td><td>{len(items)}</td></tr>"
        )
    metric_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{format_ratio(ok, count)}</td><td>{count}</td></tr>"
        for name, (ok, count) in summary["metrics"].items()
    )
    source_name = source.name
    report_stamp = f"{esc(meta.get('timestamp', '未知'))} · 模型 {esc(meta.get('model', '未知'))} · 重复 {esc(meta.get('repeat', '未知'))} 轮"
    if meta.get("ollama_available") is None:
        ollama_text = "未记录（历史结果）"
    else:
        ollama_text = "可用" if meta["ollama_available"] else "不可用"
    failed_records = [record for record in payload.get("records", []) if not record.get("passed") and not record.get("skipped")]
    records_html = "".join(
        render_record(record, questions, index)
        for index, record in enumerate(payload.get("records", []), 1)
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Agent 评估报告</title>
<style>
:root{{--ink:#202a36;--muted:#657381;--line:#dce3e8;--paper:#fff;--canvas:#f3f6f7;--teal:#087e78;--green:#18794e;--red:#b42318;--amber:#986500}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}main{{max-width:1180px;margin:0 auto;padding:32px 22px 64px}}h1{{font-size:28px;margin:0 0 6px}}h2{{font-size:19px;margin:28px 0 12px}}h3{{font-size:16px;margin:0}}h4{{font-size:13px;color:#40505e;margin:14px 0 5px}}p{{margin:4px 0}}.meta,.muted{{color:var(--muted)}}.meta{{font-size:13px}}.notice{{margin:18px 0;padding:11px 14px;border-left:3px solid var(--teal);background:#eaf5f4}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:20px 0}}.card{{background:var(--paper);border:1px solid var(--line);padding:14px 16px;border-radius:6px}}.card .value{{font-size:23px;font-weight:700;margin-top:3px}}.card .label{{color:var(--muted);font-size:12px}}.scroll{{overflow-x:auto;background:var(--paper);border:1px solid var(--line);border-radius:6px}}table{{width:100%;border-collapse:collapse;min-width:590px}}th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left}}th{{background:#f8fafb;color:#475663;font-size:12px}}tr:last-child td{{border-bottom:0}}.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.sample{{background:var(--paper);border:1px solid var(--line);border-radius:6px;margin:8px 0;overflow:hidden}}.sample.fail{{border-left:4px solid var(--red)}}.sample.skip{{border-left:4px solid var(--amber)}}.sample.pass{{border-left:4px solid var(--green)}}summary{{display:flex;align-items:center;gap:12px;padding:10px 12px;cursor:pointer;list-style:none}}summary::-webkit-details-marker{{display:none}}summary:after{{content:'＋';margin-left:auto;color:var(--muted)}}details[open]>summary:after{{content:'−'}}.sample-id{{font-weight:700;min-width:110px}}.category{{color:var(--muted);font-size:13px}}.sample-latency{{color:var(--muted);font-size:12px;margin-left:auto}}.badge{{font-size:12px;padding:2px 7px;border-radius:4px}}.badge.pass{{color:var(--green);background:#e7f4ec}}.badge.fail{{color:var(--red);background:#fff0ee}}.badge.skip{{color:var(--amber);background:#fff5dc}}.sample-body{{padding:0 14px 14px;border-top:1px solid var(--line)}}.sample-body section{{padding-top:5px}}.checks{{display:flex;flex-wrap:wrap;gap:6px}}.check{{font-size:12px;border:1px solid var(--line);border-radius:4px;padding:2px 7px}}.check.ok{{color:var(--green)}}.check.bad{{color:var(--red)}}.check.unknown{{color:var(--muted)}}pre{{margin:5px 0;padding:10px;overflow:auto;max-height:280px;background:#f5f7f8;border:1px solid #e6eaed;border-radius:4px;white-space:pre-wrap;word-break:break-word;font:12px/1.5 ui-monospace,Consolas,monospace}}.preserve{{white-space:pre-wrap;overflow-wrap:anywhere}}ul{{margin:4px 0;padding-left:20px}}.error{{color:var(--red)}}.actions{{display:flex;gap:8px;margin:14px 0}}button{{border:1px solid var(--line);background:white;padding:7px 11px;border-radius:4px;color:var(--ink);cursor:pointer}}footer{{margin-top:26px;color:var(--muted);font-size:12px}}@media(max-width:720px){{main{{padding:20px 12px 40px}}.cards{{grid-template-columns:repeat(2,1fr)}}.two-col{{grid-template-columns:1fr}}summary{{gap:7px;flex-wrap:wrap}}.sample-id{{min-width:auto}}.sample-latency{{margin-left:0}}}}
</style></head><body><main>
<h1>Agent 评估报告</h1><p class="meta">{report_stamp} · 数据文件 {esc(source_name)}</p>
<div class="notice">固定评估集结果用于回归比较，不代表真实用户场景的总体准确率。跳过样本不计入通过率；历史 JSON 未记录的字段显示为未测。</div>
<div class="cards"><div class="card"><div class="label">端到端通过</div><div class="value">{summary['passed']}/{summary['active']}</div></div><div class="card"><div class="label">失败</div><div class="value">{summary['failed']}</div></div><div class="card"><div class="label">跳过</div><div class="value">{summary['skipped']}</div></div><div class="card"><div class="label">总样本记录</div><div class="value">{summary['total']}</div></div></div>
<div class="two-col"><section><h2>按能力统计</h2><div class="scroll"><table><thead><tr><th>能力</th><th>通过</th><th>有效样本</th></tr></thead><tbody>{metric_rows}</tbody></table></div></section><section><h2>按样本类别</h2><div class="scroll"><table><thead><tr><th>类别</th><th>通过</th><th>失败</th><th>跳过</th><th>记录数</th></tr></thead><tbody>{''.join(category_rows)}</tbody></table></div></section></div>
<h2>运行信息</h2><div class="scroll"><table><tbody><tr><th>模型</th><td>{esc(meta.get('model', '未记录'))}</td><th>Ollama</th><td>{esc(ollama_text)}</td></tr><tr><th>模型接口</th><td>{esc(meta.get('base_url', '旧结果未记录'))}</td><th>数据集</th><td>{esc(meta.get('dataset', '未记录'))}</td></tr><tr><th>运行时间</th><td>{esc(meta.get('timestamp', '未记录'))}</td><th>总耗时</th><td>{esc(meta.get('elapsed_seconds', '未记录'))} 秒</td></tr><tr><th>重复轮数</th><td>{esc(meta.get('repeat', '旧结果未记录'))}</td><th>递归上限</th><td>{esc(meta.get('recursion_limit', '未记录'))}</td></tr><tr><th>平均延迟</th><td>{esc(stored_summary.get('latency_avg_ms', '未记录'))} ms</td><th>P95 延迟</th><td>{esc(stored_summary.get('latency_p95_ms', '未记录'))} ms</td></tr><tr><th>平均 token</th><td>{esc(stored_summary.get('tokens_avg', '未记录'))}</td><th>数据集 SHA-256</th><td><code>{esc(meta.get('dataset_sha256', '旧结果未记录'))}</code></td></tr></tbody></table></div>
<h2>逐样本结果</h2><div class="actions"><button onclick="document.querySelectorAll('.sample').forEach(x=>x.open=true)">全部展开</button><button onclick="document.querySelectorAll('.sample').forEach(x=>x.open=false)">全部收起</button><button onclick="document.querySelectorAll('.sample.fail,.sample.skip').forEach(x=>x.open=true)">展开失败与跳过</button></div>
{records_html or '<p class="muted">结果文件没有样本记录。</p>'}
<footer>生成器：backend/scripts/render_eval_report.py · 原始 JSON：{esc(source_name)} · 能力未被样本断言或原始文件未保存时会显示“未测”。</footer>
</main></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render Agent evaluation JSON to HTML")
    parser.add_argument("result", type=Path, help="runner output JSON file")
    parser.add_argument("--output", type=Path, help="HTML output path; defaults beside JSON")
    args = parser.parse_args()
    source = args.result.resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    target = args.output.resolve() if args.output else source.with_suffix(".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_html(payload, source), encoding="utf-8")
    summary = summarize(payload.get("records") or [])
    print(f"Report: {target}")
    print(
        f"Pass {summary['passed']}/{summary['active']}; "
        f"failed {summary['failed']}; skipped {summary['skipped']}"
    )


if __name__ == "__main__":
    main()
