#!/usr/bin/env python3
"""Build a small static HTML view for docs/*.md.

This is intentionally dependency-free so the docs can be regenerated on the
PoC server without installing a documentation framework.
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "html"
CSS_PATH = DOCS / "assets" / "docs-site.css"
SEARCH_JS_PATH = DOCS / "assets" / "docs-search.js"
SEARCH_EXCLUDED_PATHS = {"archive/integration/integration-detail-log.md"}

ACTIVE_ORDER = [
    "README.md",
    "goal.md",
    "project-context.md",
    "scope.md",
    "service-demo-scenario.md",
    "ops/runbook-current-demo.md",
    "okdong-productivity-kpi.md",
    "kagenti-operator-assistant.md",
    "dashboard-information-structure.md",
    "dashboard-policy.md",
    "device-status-policy.md",
    "device-service-binding.md",
    "current-demo-path.md",
    "repo-structure.md",
    "roadmap.md",
    "docs-cleanup-plan.md",
]


DISPLAY_TITLES = {
    "README.md": "문서 안내",
    "goal.md": "시스템 구축 목표",
    "docs-cleanup-plan.md": "문서 정리 계획",
    "project-context.md": "프로젝트 배경",
    "scope.md": "프로젝트 범위",
    "service-demo-scenario.md": "서비스 데모 시나리오",
    "current-demo-path.md": "현재 데모 흐름",
    "okdong-productivity-kpi.md": "옥동 생산성 KPI",
    "dashboard-information-structure.md": "대시보드 정보 구조",
    "dashboard-policy.md": "대시보드 판단 기준",
    "device-status-policy.md": "DeviceStatus 정책",
    "device-service-binding.md": "디바이스-서비스 바인딩",
    "kagenti-operator-assistant.md": "Kagenti 운영 보조 Agent",
    "repo-structure.md": "레포 구조",
    "roadmap.md": "로드맵",
    "ops/runbook-current-demo.md": "현재 데모 운영 Runbook",
    "ops/troubleshooting-network.md": "네트워크 트러블슈팅",
    "ops/edge-node-join-check.md": "Edge 노드 조인 점검",
    "ops/node-join-check.md": "노드 조인 점검",
    "ops/pod-connectivity-check.md": "파드 통신 점검",
    "ops/node-spec-template.md": "노드 실측 사양표",
    "archive/integration/integration-summary.md": "통합 문서 요약",
    "archive/integration/integration-doc.md": "통합 문서",
    "archive/integration/integration-detail-log.md": "통합 상세 로그",
    "archive/integration/handoff-legacy.md": "과거 인수인계",
    "archive/embedded-conference/cost-model-and-runtime-method.md": "비용 모델 안내",
    "archive/legacy-orchestration/cost-model-and-runtime-method.md": "비용 모델과 런타임 방식",
    "archive/legacy-orchestration/architecture.md": "Legacy 오케스트레이션 아키텍처",
    "archive/legacy-orchestration/system-overview.md": "Legacy 시스템 개요",
    "archive/research/README.md": "연구 초안 안내",
    "archive/research/evaluation-plan.md": "평가 계획",
    "archive/research/paper-strategy.md": "논문 전략",
    "archive/research/research-topics.md": "연구 주제 정리",
    "archive/research/venue-strategy.md": "투고처 전략",
    "archive/research/writing-checklist.md": "논문 작성 체크리스트",
    "archive/embedded-conference/experiments/selective-replanning-progress-2026-04-23.md": "Selective Replanning 진행 기록",
    "archive/embedded-conference/experiments/selective-replanning-results-2026-04-23.md": "Selective Replanning 결과 기록",
    "archive/embedded-conference/archive/selective-replanning-2026-04-23/figures/README.md": "Selective Replanning 그림 자료",
}


def md_files() -> list[Path]:
    files = sorted(DOCS.rglob("*.md"))
    files = [p for p in files if "/html/" not in p.as_posix()]
    order = {name: idx for idx, name in enumerate(ACTIVE_ORDER)}

    def key(p: Path):
        rel = p.relative_to(DOCS).as_posix()
        active = 0 if not rel.startswith("archive/") else 1
        return (active, order.get(rel, 999), rel)

    return sorted(files, key=key)


def title_of(path: Path, text: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            return strip_inline(m.group(1))
    return path.stem.replace("-", " ")


def display_title(rel_or_path, text: str) -> str:
    rel = rel_or_path.as_posix() if isinstance(rel_or_path, Path) else str(rel_or_path)
    try:
        rel = Path(rel).relative_to(DOCS).as_posix()
    except ValueError:
        pass
    return DISPLAY_TITLES.get(rel, title_of(Path(rel), text))


def short_desc(text: str, limit: int = 72) -> str:
    value = strip_inline(text).replace("이 문서는 ", "").strip()
    value = re.sub(r"\s+", " ", value)
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def first_paragraph(text: str) -> str:
    lines: list[str] = []
    in_code = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith("#") or line.startswith("|"):
            if lines:
                break
            continue
        if re.match(r"^[-*+]\s+", line) or re.match(r"^\d+\.\s+", line):
            if lines:
                break
            continue
        lines.append(line)
        if len(" ".join(lines)) > 140:
            break
    return strip_inline(" ".join(lines))[:180]


def strip_inline(s: str) -> str:
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"[*_~]", "", s)
    return html.unescape(s).strip()


def slugify(text: str) -> str:
    text = strip_inline(text).lower()
    text = re.sub(r"[^0-9a-z가-힣_-]+", "-", text)
    return text.strip("-") or "section"


def rel_to_asset(from_html: Path, asset: Path) -> str:
    return Path(os.path.relpath(asset, from_html.parent)).as_posix()


def format_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def generated_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def rel_to_css(from_html: Path) -> str:
    return rel_to_asset(from_html, CSS_PATH)


def rel_to_search_index(from_html: Path) -> str:
    return rel_to_asset(from_html, OUT / "search-index.json")


def rel_to_search_js(from_html: Path) -> str:
    return rel_to_asset(from_html, SEARCH_JS_PATH)


def out_path_for(md: Path) -> Path:
    rel = md.relative_to(DOCS)
    return OUT / rel.with_suffix(".html")


def href_for(from_html: Path, current_md: Path, target_md_rel: str) -> str:
    clean = target_md_rel.split("#", 1)
    path_part = clean[0]
    anchor = "#" + clean[1] if len(clean) > 1 else ""
    if not path_part.endswith(".md"):
        return target_md_rel
    source_target = (current_md.parent / path_part).resolve()
    try:
        rel_to_docs = source_target.relative_to(DOCS)
    except ValueError:
        return target_md_rel
    target_html = (OUT / rel_to_docs).with_suffix(".html")
    rel = Path(__import__('os').path.relpath(target_html, from_html.parent))
    return rel.as_posix() + anchor


def inline_md(s: str, current_html: Path, current_md: Path) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"@@INLINE{len(placeholders)-1}@@"

    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{m.group(1)}</code>"), s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", s)
    s = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", s)

    def link(m: re.Match[str]) -> str:
        label, url = m.group(1), html.unescape(m.group(2))
        if url.startswith("/home/") or url.startswith("/") and not url.startswith("//"):
            return stash(f'<code>{html.escape(url)}</code>')
        href = href_for(current_html, current_md, url) if url.endswith(".md") or ".md#" in url else html.escape(url, quote=True)
        return stash(f'<a href="{href}">{label}</a>')

    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, s)
    for idx, value in enumerate(placeholders):
        s = s.replace(f"@@INLINE{idx}@@", value)
    return s


def render_table(lines: list[str], current_html: Path, current_md: Path) -> str:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(cells)
    if len(rows) < 2:
        return "".join(f"<p>{inline_md(line, current_html, current_md)}</p>" for line in lines)
    head = rows[0]
    body = rows[2:] if re.match(r"^:?-{3,}:?$", rows[1][0]) else rows[1:]
    out = ["<div class=\"table-wrap\"><table>", "<thead><tr>"]
    out += [f"<th>{inline_md(c, current_html, current_md)}</th>" for c in head]
    out += ["</tr></thead>", "<tbody>"]
    for row in body:
        out.append("<tr>")
        for c in row:
            out.append(f"<td>{inline_md(c, current_html, current_md)}</td>")
        out.append("</tr>")
    out += ["</tbody></table></div>"]
    return "\n".join(out)


def render_markdown(text: str, current_html: Path, current_md: Path) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        nonlocal para
        if para:
            out.append(f"<p>{inline_md(' '.join(x.strip() for x in para), current_html, current_md)}</p>")
            para = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            if not in_code:
                flush_para()
                in_code = True
                code_lang = stripped[3:].strip()
                code_lines = []
            else:
                lang_attr = f' data-lang="{html.escape(code_lang)}"' if code_lang else ""
                code = html.escape("\n".join(code_lines))
                out.append(f"<pre{lang_attr}><code>{code}</code></pre>")
                in_code = False
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_para()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            out.append(render_table(table_lines, current_html, current_md))
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            title = m.group(2).strip()
            tag = f"h{level}"
            out.append(f'<{tag} id="{slugify(title)}">{inline_md(title, current_html, current_md)}</{tag}>' )
            i += 1
            continue
        if stripped.startswith(">"):
            flush_para()
            quote_lines = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append(f"<blockquote>{render_markdown(chr(10).join(quote_lines), current_html, current_md)}</blockquote>")
            continue
        if re.match(r"^[-*+]\s+", stripped):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^[-*+]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*+]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline_md(item, current_html, current_md)}</li>" for item in items) + "</ul>")
            continue
        if re.match(r"^\d+\.\s+", stripped):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[i].strip()))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline_md(item, current_html, current_md)}</li>" for item in items) + "</ol>")
            continue
        para.append(line)
        i += 1
    flush_para()
    return "\n".join(out)


def plain_text_for_search(text: str) -> str:
    cleaned: list[str] = []
    in_code = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            cleaned.append(stripped)
            continue
        if not stripped:
            continue
        cleaned.append(strip_inline(stripped.lstrip("> ")))
    return re.sub(r"\s+", " ", " ".join(cleaned)).strip()


def search_box_markup(label: str, index_href: str, script_href: str = "docs-search.js") -> str:
    return f"""<section class=\"search-panel\" aria-label=\"{html.escape(label, quote=True)}\">
  <div class=\"search-head\">
    <strong>{html.escape(label)}</strong>
    <span>제목, 경로, 본문 내용을 빠르게 찾습니다.</span>
  </div>
  <div class=\"search-box\" data-search-index=\"{html.escape(index_href, quote=True)}\">
    <div class=\"search-filters\" role=\"group\" aria-label=\"검색 범위\">
      <button type=\"button\" class=\"active\" data-search-filter=\"all\">전체</button>
      <button type=\"button\" data-search-filter=\"active\">Active</button>
      <button type=\"button\" data-search-filter=\"ops\">운영</button>
      <button type=\"button\" data-search-filter=\"archive\">Archive</button>
    </div>
    <input id=\"doc-search-input\" type=\"search\" placeholder=\"예: device status, dashboard, KPI, runbook\" autocomplete=\"off\">
    <div id=\"doc-search-results\" class=\"search-results\" aria-live=\"polite\"></div>
  </div>
  <script src=\"{html.escape(script_href, quote=True)}\" defer></script>
</section>"""


def home_intro_markup() -> str:
    return """<section class=\"home-intro\" aria-label=\"문서 정리 기준\">
  <a class=\"intro-card primary\" href=\"goal.html\">
    <strong>시스템 구축 목표</strong>
    <span>혼합 디바이스 edge AI 서비스 데모를 운영 관점에서 보이게 만드는 것이 현재 기준입니다.</span>
  </a>
  <a class=\"intro-card\" href=\"docs-cleanup-plan.html\">
    <strong>문서 정리 기준</strong>
    <span>Active와 운영 문서를 먼저 보고, Archive는 과거 맥락 확인용으로 분리합니다.</span>
  </a>
  <div class=\"intro-card muted\">
    <strong>Archive는 과거 맥락</strong>
    <span>workflow/offloading/replanning 자료는 현재 구축 목표가 아니라 보관 자료로 봅니다.</span>
  </div>
</section>"""


def render_search_index(files: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for md in files:
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(DOCS).as_posix()
        url = Path(rel).with_suffix(".html").as_posix()
        items.append({
            "title": display_title(rel, text),
            "path": rel,
            "url": url,
            "group": group_of(rel),
            "filter": filter_of(rel),
            "search_excluded": is_search_excluded(rel),
            "description": short_desc(first_paragraph(text)),
            "text": plain_text_for_search(text)[:12000],
        })
    (OUT / "search-index.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def group_of(rel: str) -> str:
    if rel.startswith("archive/"):
        return "Archive"
    if rel.startswith("ops/"):
        return "운영 문서"
    return "Active 문서"


def filter_of(rel: str) -> str:
    if rel.startswith("archive/"):
        return "archive"
    if rel.startswith("ops/"):
        return "ops"
    return "active"


def is_search_excluded(rel: str) -> bool:
    return rel in SEARCH_EXCLUDED_PATHS


def archive_banner(rel: str) -> str:
    return f"""<aside class=\"archive-banner\" aria-label=\"Archive 안내\">
  <strong>과거 자료</strong>
  <span>이 문서는 현재 구축 목표가 아니라 과거 연구/통합/legacy 맥락 확인용입니다. 현재 판단은 Active 문서를 우선하세요.</span>
  <code>{html.escape(rel)}</code>
</aside>"""


def sidebar(files: list[Path], current: Path) -> str:
    chunks = ['<nav class="sidebar" aria-label="문서 목록">', '<h2>문서 목록</h2>', '<ul>']
    last = None
    for md in files:
        rel = md.relative_to(DOCS).as_posix()
        group = group_of(rel)
        if group != last:
            chunks.append(f'<li class="group">{html.escape(group)}</li>')
            last = group
        title = display_title(rel, md.read_text(encoding="utf-8"))
        target = out_path_for(md)
        href = Path(__import__('os').path.relpath(target, current.parent)).as_posix()
        chunks.append(f'<li><a href="{href}">{html.escape(title)}</a></li>')
    chunks += ["</ul>", "</nav>"]
    return "\n".join(chunks)


def headings_of(text: str) -> list[tuple[int, str, str]]:
    headings: list[tuple[int, str, str]] = []
    in_code = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{2,3})\s+(.+)$", stripped)
        if not m:
            continue
        level = len(m.group(1))
        title = strip_inline(m.group(2).strip())
        headings.append((level, title, slugify(title)))
    return headings


def toc_for(text: str) -> str:
    headings = headings_of(text)
    if not headings:
        return '<aside class="toc" aria-label="문서 목차"><h2>이 문서</h2><p class="empty">목차 없음</p></aside>'
    items = []
    for level, title, slug in headings[:24]:
        cls = "toc-h3" if level == 3 else "toc-h2"
        items.append(f'<li class="{cls}"><a href="#{slug}">{html.escape(title)}</a></li>')
    return '<aside class="toc" aria-label="문서 목차"><h2>이 문서</h2><ol>' + "\n".join(items) + '</ol></aside>'


def render_doc(md: Path, files: list[Path]) -> None:
    text = md.read_text(encoding="utf-8")
    rel = md.relative_to(DOCS).as_posix()
    title = display_title(rel, text)
    out_path = out_path_for(md)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = render_markdown(text, out_path, md)
    is_archive = rel.startswith("archive/")
    kind = "Archive" if is_archive else "Active"
    desc = short_desc(first_paragraph(text))
    page_class = "doc archive" if is_archive else "doc"
    archive_note = archive_banner(rel) if is_archive else ""
    html_text = f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="{html.escape(rel_to_css(out_path))}">
</head>
<body>
  <div class="site-shell">
    <div class="topbar">
      <div class="topbar-left">
        <a href="{Path(os.path.relpath(OUT / 'index.html', out_path.parent)).as_posix()}">← 문서 홈</a>
        <a class="edit-link" href="/__edit?file={html.escape(rel, quote=True)}">편집</a>
      </div>
      <span>{html.escape(rel)}</span>
    </div>
    {search_box_markup("문서 검색", rel_to_search_index(out_path), rel_to_search_js(out_path))}
    <div class="layout">
      {sidebar(files, out_path)}
      <article class="{page_class}">
        <header class="doc-header">
          <p class="eyebrow">{html.escape(kind)} 문서</p>
          <h1>{html.escape(title)}</h1>
          <p class="subtitle">{html.escape(desc) if desc else '기존 Markdown 문서를 HTML로 변환한 읽기용 페이지입니다.'}</p>
          <div class="meta">
            <span class="badge kind">{html.escape(kind)}</span>
            <span class="badge">원본: {html.escape(rel)}</span>
            <span class="badge">수정: {html.escape(format_mtime(md))}</span>
            <span class="badge">HTML 생성: {html.escape(generated_at())}</span>
          </div>
        </header>
        {archive_note}
        <div class="doc-body">
          {body}
        </div>
      </article>
      {toc_for(text)}
    </div>
  </div>
  <footer>Generated from docs/*.md</footer>
</body>
</html>
'''
    out_path.write_text(html_text, encoding="utf-8")


def render_index(files: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Path]] = {"Active 문서": [], "운영 문서": [], "Archive": []}
    for md in files:
        groups[group_of(md.relative_to(DOCS).as_posix())].append(md)
    sections = []
    for name, group_files in groups.items():
        if not group_files:
            continue
        cards = []
        for md in group_files:
            text = md.read_text(encoding="utf-8")
            rel = md.relative_to(DOCS).as_posix()
            title = display_title(rel, text)
            desc = short_desc(first_paragraph(text)) or rel
            href = Path(rel).with_suffix(".html").as_posix()
            cards.append(f'<li><a class="doc-card" href="{href}"><strong>{html.escape(title)}</strong><span>{html.escape(desc)}</span><small>수정: {html.escape(format_mtime(md))}</small></a></li>')
        sections.append(f'<h2 class="section-title">{html.escape(name)}</h2><ul class="card-grid">' + "\n".join(cards) + "</ul>")
    index = f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>KubeEdge PoC 문서 HTML 보기</title>
  <link rel="stylesheet" href="{html.escape(rel_to_css(OUT / 'index.html'))}">
</head>
<body>
  <main class="home">
    <article class="home-card">
      <header class="home-hero">
        <p class="eyebrow">KubeEdge Edge AI PoC</p>
        <h1>문서 HTML 보기</h1>
        <p class="subtitle">
          기존 <code>docs/*.md</code> 문서를 브라우저에서 읽기 좋게 변환한 정적 HTML 목록이다.
          원본 Markdown은 그대로 유지하고, 이 디렉터리는 읽기용 산출물로 재생성할 수 있다.
        </p>
        <div class="meta">
          <span class="badge kind">Active 문서 우선</span>
          <span class="badge">운영자 기준</span>
          <span class="badge">Markdown 원본 유지</span>
          <span class="badge">정적 HTML</span>
          <span class="badge">HTML 생성: {html.escape(generated_at())}</span>
          <a class="badge edit-badge" href="/__edit">문서 편집 열기</a>
        </div>
      </header>
      {home_intro_markup()}
      <div class="home-search">
        {search_box_markup("문서 전체 검색", rel_to_search_index(OUT / 'index.html'), rel_to_search_js(OUT / 'index.html'))}
      </div>
      <div class="home-body">
        {''.join(sections)}
      </div>
    </article>
  </main>
  <footer>docs/html · generated by scripts/build-docs-html.py</footer>
</body>
</html>
'''
    (OUT / "index.html").write_text(index, encoding="utf-8")


def main() -> None:
    files = md_files()
    render_index(files)
    render_search_index(files)
    for md in files:
        render_doc(md, files)
    print(f"generated {len(files)} docs into {OUT}")


if __name__ == "__main__":
    main()
