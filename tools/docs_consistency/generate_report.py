#!/usr/bin/env python3
"""Generate a single-file docs/code consistency HTML report.

Run from repository root:

    python3 tools/docs_consistency/generate_report.py
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
import sys

# Allow running as `python3 tools/docs_consistency/generate_report.py`.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from rules import DOC_FILES, CODE_FILES, Finding, RuleResult, load_corpus, run_rules  # noqa: E402


REPORT_PATH = Path("docs/generated/consistency-report.html")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def status_class(status: str) -> str:
    return status.lower()


def render_badge(status: str) -> str:
    return f'<span class="badge {status_class(status)}">{escape(status)}</span>'


def render_summary(results: list[RuleResult]) -> str:
    counts = Counter(r.status for r in results)
    cards = []
    for status in ["PASS", "WARN", "FAIL"]:
        cards.append(
            f"""
            <div class="summary-card {status_class(status)}-card">
              <div class="summary-label">{status}</div>
              <div class="summary-value">{counts.get(status, 0)}</div>
            </div>
            """
        )
    return "\n".join(cards)


def render_evidence(result: RuleResult) -> str:
    items: list[str] = []
    for finding in result.findings[:12]:
        items.append(
            f"""
            <li>
              {render_badge(finding.status)}
              <code>{escape(finding.file)}:{finding.line}</code>
              <div class="evidence-text">{escape(finding.evidence)}</div>
              <div class="message">{escape(finding.message)}</div>
            </li>
            """
        )
    if result.evidence:
        for ev in result.evidence[:6]:
            items.append(f'<li>{render_badge("PASS")} <span class="evidence-text">{escape(ev)}</span></li>')
    if not items:
        items.append('<li><span class="muted">No explicit evidence found.</span></li>')
    return "\n".join(items)


def render_rule_results(results: list[RuleResult]) -> str:
    rows = []
    for result in results:
        files = ", ".join(result.matched_files) if result.matched_files else "-"
        rows.append(
            f"""
            <section class="rule-card {status_class(result.status)}-border">
              <div class="rule-head">
                <h3>{escape(result.name)}</h3>
                {render_badge(result.status)}
              </div>
              <div class="meta"><strong>Matched files:</strong> {escape(files)}</div>
              <details open>
                <summary>Evidence</summary>
                <ul class="evidence-list">{render_evidence(result)}</ul>
              </details>
              <div class="fix"><strong>Recommended fix:</strong> {escape(result.recommended_fix)}</div>
            </section>
            """
        )
    return "\n".join(rows)


def collect_file_findings(results: list[RuleResult]) -> dict[str, list[Finding]]:
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for result in results:
        for finding in result.findings:
            grouped[finding.file].append(finding)
    return dict(sorted(grouped.items()))


def render_file_findings(results: list[RuleResult]) -> str:
    grouped = collect_file_findings(results)
    if not grouped:
        return '<p class="ok-text">No file-level WARN/FAIL findings.</p>'
    sections = []
    for file, findings in grouped.items():
        lis = []
        for finding in findings:
            lis.append(
                f"""
                <li>
                  {render_badge(finding.status)}
                  <strong>{escape(finding.rule)}</strong>
                  <code>line {finding.line}</code>
                  <div class="evidence-text">{escape(finding.evidence)}</div>
                  <div class="message">{escape(finding.message)}</div>
                </li>
                """
            )
        sections.append(f"<section class='file-card'><h3>{escape(file)}</h3><ul>{''.join(lis)}</ul></section>")
    return "\n".join(sections)


def render_recommended_patches(results: list[RuleResult]) -> str:
    seen = set()
    snippets = []
    for result in results:
        if result.recommended_fix in seen:
            continue
        seen.add(result.recommended_fix)
        status = result.status
        snippets.append(
            f"""
            <div class="patch-card">
              <div>{render_badge(status)} <strong>{escape(result.name)}</strong></div>
              <pre>{escape(result.recommended_fix)}</pre>
            </div>
            """
        )
    return "\n".join(snippets)


def render_inputs() -> str:
    docs = "".join(f"<li><code>{escape(p)}</code></li>" for p in DOC_FILES)
    code = "".join(f"<li><code>{escape(p)}</code></li>" for p in CODE_FILES)
    return f"""
    <details>
      <summary>Checked inputs</summary>
      <div class="columns">
        <div><h3>Docs</h3><ul>{docs}</ul></div>
        <div><h3>Code</h3><ul>{code}</ul></div>
      </div>
    </details>
    """


def build_html(results: list[RuleResult], generated_at: str) -> str:
    fail_count = sum(1 for r in results if r.status == "FAIL")
    warn_count = sum(1 for r in results if r.status == "WARN")
    overall = "FAIL" if fail_count else "WARN" if warn_count else "PASS"
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Docs-Code Consistency Report</title>
  <style>
    :root {{
      --bg: #0f172a;
      --panel: #111827;
      --panel2: #1f2937;
      --text: #e5e7eb;
      --muted: #9ca3af;
      --pass: #22c55e;
      --warn: #f59e0b;
      --fail: #ef4444;
      --border: #374151;
      --code: #020617;
    }}
    body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); line-height: 1.55; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 32px 20px 64px; }}
    h1, h2, h3 {{ line-height: 1.25; }}
    h1 {{ margin-bottom: 4px; font-size: 30px; }}
    h2 {{ margin-top: 36px; padding-top: 12px; border-top: 1px solid var(--border); }}
    a {{ color: #93c5fd; }}
    code {{ background: var(--code); color: #bfdbfe; border: 1px solid #1e293b; border-radius: 5px; padding: 1px 5px; }}
    pre {{ white-space: pre-wrap; background: var(--code); border: 1px solid #1e293b; border-radius: 10px; padding: 14px; overflow-x: auto; }}
    .subtitle {{ color: var(--muted); margin-top: 0; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 22px 0; }}
    .summary-card, .rule-card, .file-card, .patch-card, details {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }}
    .summary-card {{ text-align: center; }}
    .summary-label {{ color: var(--muted); font-weight: 700; }}
    .summary-value {{ font-size: 36px; font-weight: 800; }}
    .pass-card {{ box-shadow: inset 0 3px 0 var(--pass); }}
    .warn-card {{ box-shadow: inset 0 3px 0 var(--warn); }}
    .fail-card {{ box-shadow: inset 0 3px 0 var(--fail); }}
    .rule-card {{ margin: 16px 0; }}
    .pass-border {{ border-left: 5px solid var(--pass); }}
    .warn-border {{ border-left: 5px solid var(--warn); }}
    .fail-border {{ border-left: 5px solid var(--fail); }}
    .rule-head {{ display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }}
    .rule-head h3 {{ margin: 0 0 8px; }}
    .badge {{ display: inline-block; min-width: 48px; text-align: center; border-radius: 999px; padding: 2px 9px; font-size: 12px; font-weight: 800; color: #020617; }}
    .badge.pass {{ background: var(--pass); }}
    .badge.warn {{ background: var(--warn); }}
    .badge.fail {{ background: var(--fail); color: white; }}
    .meta, .message, .muted {{ color: var(--muted); }}
    .fix {{ margin-top: 12px; padding: 12px; background: var(--panel2); border-radius: 10px; }}
    .evidence-list li, .file-card li {{ margin: 12px 0; }}
    .evidence-text {{ margin: 5px 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #d1d5db; }}
    .file-card {{ margin: 14px 0; }}
    .patch-card {{ margin: 12px 0; }}
    .ok-text {{ color: var(--pass); font-weight: 700; }}
    .columns {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; }}
    @media (max-width: 760px) {{ .summary-grid, .columns {{ grid-template-columns: 1fr; }} .rule-head {{ flex-direction: column; }} }}
  </style>
</head>
<body>
  <main>
    <h1>Docs-Code Consistency Report</h1>
    <p class="subtitle">Generated at {escape(generated_at)} · Overall {render_badge(overall)}</p>

    <h2>1. Summary</h2>
    <div class="summary-grid">{render_summary(results)}</div>
    {render_inputs()}

    <h2>2. Rule Results</h2>
    {render_rule_results(results)}

    <h2>3. File-level Findings</h2>
    {render_file_findings(results)}

    <h2>4. Recommended Patches</h2>
    {render_recommended_patches(results)}
  </main>
</body>
</html>
"""


def main() -> int:
    root = repo_root()
    corpus = load_corpus(root)
    results = run_rules(corpus)
    generated_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    html = build_html(results, generated_at)
    report = root / REPORT_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(html, encoding="utf-8")

    counts = Counter(r.status for r in results)
    print(f"generated: {report}")
    print(f"PASS={counts.get('PASS', 0)} WARN={counts.get('WARN', 0)} FAIL={counts.get('FAIL', 0)}")
    for result in results:
        print(f"{result.status:4} {result.name} findings={len(result.findings)}")
    return 1 if counts.get("FAIL", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
