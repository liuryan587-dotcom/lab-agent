import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "render_eval_report.py"
SPEC = importlib.util.spec_from_file_location("render_eval_report", SCRIPT_PATH)
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


def test_report_counts_pass_fail_skip_separately_and_escapes_content(tmp_path):
    payload = {
        "meta": {"model": "test-model", "timestamp": "2026-01-01", "repeat": 1},
        "summary": {"latency_avg_ms": 12, "latency_p95_ms": 20, "tokens_avg": 30},
        "records": [
            {
                "id": "R01", "category": "rag", "question": "<script>alert(1)</script>",
                "passed": True, "checks": {"doc": True}, "latency_ms": 12,
                "expect": {"doc": "rules"}, "tools": ["search_lab_docs"],
            },
            {
                "id": "T01", "category": "tool", "passed": False,
                "checks": {"tools": False}, "fails": ["wrong tool"],
                "latency_ms": 20,
            },
            {
                "id": "R02", "category": "rag", "passed": False,
                "skipped": True, "fails": ["Ollama unavailable"], "latency_ms": 0,
            },
        ],
    }

    summary = report.summarize(payload["records"])
    assert (summary["passed"], summary["failed"], summary["skipped"]) == (1, 1, 1)
    html = report.build_html(payload, tmp_path / "result.json")
    assert "1/2" in html
    assert "Ollama unavailable" in html
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "工具参数" in html
    assert "未测" in html
