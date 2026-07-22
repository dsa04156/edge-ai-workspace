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
SEARCH_EXCLUDED_PATHS = {"archive/integration/통합-상세-기록.md"}
DESIGN_HISTORY_PATHS = {
    "일일-기록.md",
    "대시보드-화면-설계.md",
    "자원-증강-가상디바이스-대시보드.md",
    "런타임-자원-증강-데모-워크플로.md",
}

WIKI_ORDER = [
    "wiki/지식-지도.md",
    "wiki/운영-규칙.md",
    "wiki/변경-기록.md",
    "wiki/운영-모델.md",
    "wiki/현재-데모-흐름.md",
    "wiki/상태와-텔레메트리.md",
    "wiki/대시보드와-kpi.md",
    "wiki/운영-진입점.md",
    "wiki/2차년도-설계-트랙.md",
]

ACTIVE_ORDER = [
    "문서-안내.md",
    "시스템-구축-목표.md",
    "프로젝트-배경.md",
    "프로젝트-범위.md",
    "원시-텔레메트리-데이터-플레인.md",
    "서비스-데모-시나리오.md",
    "옥동-생산성-kpi.md",
    "카젠티-운영-보조-에이전트.md",
    "2차년도-가상디바이스-워크플로-설계.md",
    "대시보드-정보-구조.md",
    "대시보드-판단-정책.md",
    "물리-디바이스-상태-정책.md",
    "쿠버엣지-엣지엑스-모델-매핑.md",
    "디바이스-서비스-연결.md",
    "현재-데모-경로.md",
    "저장소-구조.md",
    "단계별-추진계획.md",
    "문서-정리-계획.md",
]

OPS_ORDER = [
    "ops/현재-데모-운영-절차.md",
    "ops/엣지엑스-코어데이터-1000-디바이스-부하검증.md",
    "ops/중앙-메시지버스-재구축-절차.md",
    "ops/대시보드-검증.md",
    "ops/gpu-hami-런타임-운영.md",
    "ops/네트워크-문제해결.md",
    "ops/엣지-노드-조인-점검.md",
    "ops/노드-조인-점검.md",
    "ops/파드-연결성-점검.md",
    "ops/노드-실측-사양표.md",
]


DISPLAY_TITLES = {
    "문서-안내.md": "문서 안내",
    "시스템-구축-목표.md": "시스템 구축 목표",
    "문서-정리-계획.md": "문서 정리 계획",
    "프로젝트-배경.md": "프로젝트 배경",
    "프로젝트-범위.md": "프로젝트 범위",
    "서비스-데모-시나리오.md": "서비스 데모 시나리오",
    "현재-데모-경로.md": "현재 데모 경로",
    "옥동-생산성-kpi.md": "옥동 생산성 KPI",
    "대시보드-정보-구조.md": "대시보드 정보 구조",
    "대시보드-판단-정책.md": "대시보드 판단 정책",
    "물리-디바이스-상태-정책.md": "물리 디바이스 상태 정책",
    "쿠버엣지-엣지엑스-모델-매핑.md": "쿠버엣지-엣지엑스 모델 매핑",
    "디바이스-서비스-연결.md": "디바이스-서비스 연결",
    "카젠티-운영-보조-에이전트.md": "카젠티 운영 보조 에이전트",
    "2차년도-가상디바이스-워크플로-설계.md": "2차년도 가상디바이스·워크플로 설계",
    "원시-텔레메트리-데이터-플레인.md": "원시 텔레메트리 데이터 플레인",
    "저장소-구조.md": "저장소 구조",
    "단계별-추진계획.md": "단계별 추진계획",
    "wiki/지식-지도.md": "쿠버엣지 PoC 지식 지도",
    "wiki/운영-규칙.md": "위키 운영 규칙",
    "wiki/변경-기록.md": "위키 변경 기록",
    "wiki/운영-모델.md": "운영 모델",
    "wiki/현재-데모-흐름.md": "현재 데모 흐름 요약",
    "wiki/상태와-텔레메트리.md": "상태와 텔레메트리",
    "wiki/대시보드와-kpi.md": "대시보드와 KPI 모델",
    "wiki/운영-진입점.md": "운영 진입점",
    "wiki/2차년도-설계-트랙.md": "2차년도 설계 트랙",
    "ops/현재-데모-운영-절차.md": "현재 데모 운영 절차",
    "ops/엣지엑스-코어데이터-1000-디바이스-부하검증.md": "EdgeX Core Data 1,000 디바이스 부하 검증",
    "ops/중앙-메시지버스-재구축-절차.md": "중앙 메시지버스 배치 재구축 절차",
    "ops/네트워크-문제해결.md": "네트워크 문제 해결",
    "ops/엣지-노드-조인-점검.md": "엣지 노드 조인 점검",
    "ops/노드-조인-점검.md": "노드 조인 점검",
    "ops/파드-연결성-점검.md": "파드 연결성 점검",
    "ops/노드-실측-사양표.md": "노드 실측 사양표",
    "archive/integration/통합-요약.md": "통합 문서 요약",
    "archive/integration/통합-문서.md": "통합 문서",
    "archive/integration/통합-상세-기록.md": "통합 상세 기록",
    "archive/integration/과거-인수인계.md": "과거 인수인계",
    "archive/embedded-conference/비용-모델과-런타임-방식.md": "비용 모델 안내",
    "archive/legacy-orchestration/비용-모델과-런타임-방식.md": "비용 모델과 런타임 방식",
    "archive/legacy-orchestration/아키텍처.md": "레거시 오케스트레이션 아키텍처",
    "archive/legacy-orchestration/시스템-개요.md": "레거시 시스템 개요",
    "archive/research/연구-초안-안내.md": "연구 초안 안내",
    "archive/research/평가-계획.md": "평가 계획",
    "archive/research/논문-전략.md": "논문 전략",
    "archive/research/연구-주제.md": "연구 주제 정리",
    "archive/research/투고처-전략.md": "투고처 전략",
    "archive/research/논문-작성-점검표.md": "논문 작성 점검표",
    "archive/embedded-conference/experiments/선택적-재계획-진행-2026-04-23.md": "선택적 재계획 진행 기록",
    "archive/embedded-conference/experiments/선택적-재계획-결과-2026-04-23.md": "선택적 재계획 결과 기록",
    "archive/embedded-conference/archive/selective-replanning-2026-04-23/figures/선택적-재계획-그림-자료.md": "선택적 재계획 그림 자료",
}


def md_files() -> list[Path]:
    files = sorted(DOCS.rglob("*.md"))
    files = [p for p in files if "/html/" not in p.as_posix()]
    order = {
        **{name: idx for idx, name in enumerate(WIKI_ORDER)},
        **{name: idx for idx, name in enumerate(ACTIVE_ORDER)},
        **{name: idx for idx, name in enumerate(OPS_ORDER)},
    }
    group_order = {"wiki": 0, "active": 1, "ops": 2, "history": 3, "archive": 4}

    def key(p: Path):
        rel = p.relative_to(DOCS).as_posix()
        return (group_order[filter_of(rel)], order.get(rel, 999), rel)

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
      <button type=\"button\" data-search-filter=\"wiki\">위키</button>
      <button type=\"button\" data-search-filter=\"active\">최신 기준</button>
      <button type=\"button\" data-search-filter=\"ops\">운영</button>
      <button type=\"button\" data-search-filter=\"history\">설계 이력</button>
      <button type=\"button\" data-search-filter=\"archive\">보관</button>
    </div>
    <input id=\"doc-search-input\" type=\"search\" placeholder=\"예: device status, dashboard, KPI, runbook\" autocomplete=\"off\">
    <div id=\"doc-search-results\" class=\"search-results\" aria-live=\"polite\"></div>
  </div>
  <script src=\"{html.escape(script_href, quote=True)}\" defer></script>
</section>"""


def home_intro_markup() -> str:
    return """<section class=\"home-intro\" aria-label=\"문서 정리 기준\">
  <a class=\"intro-card primary\" href=\"wiki/지식-지도.html\">
    <strong>지식 지도</strong>
    <span>질문이 있을 때 먼저 읽고 최신 원본문서로 이동합니다.</span>
  </a>
  <a class=\"intro-card\" href=\"프로젝트-범위.html\">
    <strong>프로젝트 범위</strong>
    <span>현재 구현, 2차년도 설계, 레거시·보관 경계를 판단하는 최우선 기준입니다.</span>
  </a>
  <a class=\"intro-card\" href=\"문서-정리-계획.html\">
    <strong>문서 정리 기준</strong>
    <span>최신 기준과 운영 문서를 먼저 보고 설계 이력과 보관 자료는 필요할 때만 확인합니다.</span>
  </a>
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
    if rel.startswith("wiki/"):
        return "위키"
    if rel.startswith("archive/"):
        return "보관 문서"
    if rel.startswith("ops/"):
        return "운영 문서"
    if rel.startswith("superpowers/") or rel in DESIGN_HISTORY_PATHS:
        return "설계 이력"
    return "최신 기준 문서"


def filter_of(rel: str) -> str:
    if rel.startswith("wiki/"):
        return "wiki"
    if rel.startswith("archive/"):
        return "archive"
    if rel.startswith("ops/"):
        return "ops"
    if rel.startswith("superpowers/") or rel in DESIGN_HISTORY_PATHS:
        return "history"
    return "active"


def is_search_excluded(rel: str) -> bool:
    return rel in SEARCH_EXCLUDED_PATHS


def archive_banner(rel: str) -> str:
    return f"""<aside class=\"archive-banner\" aria-label=\"보관 문서 안내\">
  <strong>과거 자료</strong>
  <span>현재 구축 목표가 아니라 과거 연구·통합·레거시 맥락 확인용입니다. 현재 판단은 최신 기준 문서를 우선하세요.</span>
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
    kind = group_of(rel)
    desc = short_desc(first_paragraph(text))
    page_class = "doc archive" if is_archive else "doc"
    archive_note = f"        {archive_banner(rel)}\n" if is_archive else ""
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
          <p class="eyebrow">{html.escape(kind)}</p>
          <h1>{html.escape(title)}</h1>
          <p class="subtitle">{html.escape(desc) if desc else '기존 Markdown 문서를 HTML로 변환한 읽기용 페이지입니다.'}</p>
          <div class="meta">
            <span class="badge kind">{html.escape(kind)}</span>
            <span class="badge">원본: {html.escape(rel)}</span>
            <span class="badge">수정: {html.escape(format_mtime(md))}</span>
            <span class="badge">HTML 생성: {html.escape(generated_at())}</span>
          </div>
        </header>
{archive_note}        <div class="doc-body">
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
    groups: dict[str, list[Path]] = {"위키": [], "최신 기준 문서": [], "운영 문서": [], "설계 이력": [], "보관 문서": []}
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
          <span class="badge kind">Wiki 우선</span>
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
