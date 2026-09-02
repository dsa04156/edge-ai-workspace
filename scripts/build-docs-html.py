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
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DEFAULT_DOCS = DOCS
OUT = DOCS / "html"
CSS_PATH = DOCS / "assets" / "docs-site.css"
SEARCH_JS_PATH = DOCS / "assets" / "docs-search.js"
SERIAL_RECOVERY_EXPLAINER_JS_PATH = DOCS / "assets" / "serial-recovery-explainer.js"
SERIAL_RECOVERY_EXPLAINER_PATH = "400ms-복구-체험하기.md"
PUBLICATION_SECTIONS = [
    ("시작하기", "start", [
        "문서-안내.md",
        "처음부터-배우는-Edge-AI-시스템.md",
        "플랫폼-개요.md",
        "펌프-모터-이상감지-서비스.md",
        "현재-구현-상태.md",
    ]),
    ("연결 가이드", "guide", ["디바이스-서비스-연결.md", "AI-서비스-등록-가이드.md"]),
    ("운영", "ops", [
        "ops/현재-데모-운영-절차.md",
        "ops/대시보드-배포.md",
        "ops/대시보드-검증.md",
        "ops/네트워크-문제해결.md",
    ]),
    ("정책과 계약", "policy", [
        "프로젝트-범위.md",
        "대시보드-판단-정책.md",
        "가상화-노드-오류-복구시간.md",
        SERIAL_RECOVERY_EXPLAINER_PATH,
        "AI-서비스-자원-증강-부하-실험.md",
        "옥동-데이터-계약.md",
        "옥동-생산성-kpi.md",
    ]),
    ("개발 참고", "reference", ["저장소-구조.md", "단계별-추진계획.md"]),
]
PUBLIC_PATHS = [path for _, _, paths in PUBLICATION_SECTIONS for path in paths]
PUBLIC_META = {
    path: (section, filter_name, order)
    for section, filter_name, paths in PUBLICATION_SECTIONS
    for order, path in enumerate(paths)
}


DISPLAY_TITLES = {
    "AI-서비스-등록-가이드.md": "AI 서비스 등록 가이드",
    "AI-서비스-자원-증강-부하-실험.md": "AI 서비스 자원 증강 부하 실험",
    "문서-안내.md": "문서 안내",
    "처음부터-배우는-Edge-AI-시스템.md": "처음부터 배우는 Edge AI 시스템",
    "플랫폼-개요.md": "플랫폼 개요",
    "펌프-모터-이상감지-서비스.md": "펌프·모터 이상감지 서비스",
    "문서-분류-목록.md": "문서 전체 분류 목록",
    "2차년도-ETRI-실행계획.md": "2026년도 2차년도 ETRI 실행계획",
    "시스템-구축-목표.md": "시스템 구축 목표",
    "문서-정리-계획.md": "문서 정리 계획",
    "프로젝트-배경.md": "프로젝트 배경",
    "프로젝트-범위.md": "프로젝트 범위",
    "서비스-데모-시나리오.md": "서비스 데모 시나리오",
    "현재-데모-경로.md": "현재 데모 경로",
    "옥동-생산성-kpi.md": "옥동 생산성 KPI",
    "대시보드-정보-구조.md": "대시보드 정보 구조",
    "대시보드-판단-정책.md": "대시보드 판단 정책",
    "가상화-노드-오류-복구시간.md": "가상화 노드 오류 복구시간",
    "400ms-복구-체험하기.md": "400 ms 복구 체험하기",
    "물리-디바이스-상태-정책.md": "물리 디바이스 상태 정책",
    "쿠버엣지-엣지엑스-모델-매핑.md": "쿠버엣지-엣지엑스 모델 매핑",
    "디바이스-서비스-연결.md": "디바이스 연결 가이드",
    "카젠티-운영-보조-에이전트.md": "카젠티 운영 보조 에이전트",
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
    "ops/대시보드-배포.md": "대시보드 배포",
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
    if DOCS.resolve() == DEFAULT_DOCS.resolve():
        missing = [rel for rel in PUBLIC_PATHS if not (DOCS / rel).is_file()]
        if missing:
            raise FileNotFoundError(f"공개 문서가 없습니다: {', '.join(missing)}")
        return [DOCS / rel for rel in PUBLIC_PATHS]

    files = sorted(DOCS.rglob("*.md"))
    files = [p for p in files if "/html/" not in p.as_posix()]
    return files


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


def rel_to_serial_recovery_explainer_js(from_html: Path) -> str:
    return rel_to_asset(from_html, SERIAL_RECOVERY_EXPLAINER_JS_PATH)


def serial_recovery_playground_markup() -> str:
    return """<section class="recovery-lab" data-recovery-lab aria-labelledby="recovery-lab-title">
  <div class="recovery-lab-head">
    <div>
      <p class="recovery-lab-kicker">손으로 만져 보는 설명</p>
      <h2 id="recovery-lab-title">센서 쪽지가 다시 도착하는 길</h2>
      <p>아래 세 가지를 바꿔 보세요. <strong>400 ms 판정</strong>은 오류를 알아챈 뒤부터 새 쪽지를 받기까지입니다.</p>
    </div>
    <p class="recovery-lab-model">교육용 시뮬레이터 · 실제 시험 성적을 다시 계산하지 않습니다</p>
  </div>

  <div class="recovery-controls" aria-label="복구 조건 조절">
    <label class="recovery-control recovery-toggle">
      <span>아두이노를 다시 시작하게 만들기</span>
      <small>Serial 포트를 닫을 때 Uno auto-reset이 일어나는 경우</small>
      <input type="checkbox" data-recovery-reset>
      <span class="toggle-visual" aria-hidden="true"></span>
      <strong data-recovery-reset-label>꺼짐</strong>
    </label>
    <label class="recovery-control">
      <span>센서가 쪽지를 보내는 간격</span>
      <small>다시 연결된 뒤 다음 쪽지를 기다릴 수 있는 최대 시간</small>
      <input type="range" data-recovery-cadence min="100" max="1000" step="100" value="100">
      <output data-recovery-cadence-output>100 ms</output>
    </label>
    <label class="recovery-control">
      <span>오류를 알아차리는 간격</span>
      <small>사람이 체감하는 시간에는 더해지지만, 공식 400 ms 계측은 여기서 시작합니다</small>
      <input type="range" data-recovery-heartbeat min="50" max="400" step="50" value="400">
      <output data-recovery-heartbeat-output>400 ms</output>
    </label>
  </div>

  <div class="recovery-presets" aria-label="빠른 조건 선택">
    <button type="button" data-recovery-preset="current">현재 통과 구성</button>
    <button type="button" data-recovery-preset="reset">자동 리셋만 켜기</button>
    <button type="button" data-recovery-preset="slow">전송을 1초로</button>
    <button type="button" class="play-button" data-recovery-play>한 번 재생하기</button>
  </div>

  <div class="recovery-timeline" aria-label="복구 타임라인">
    <div class="recovery-not-scored">
      <span>① 오류를 알아차림</span>
      <strong data-recovery-heartbeat-timeline>400 ms</strong>
      <small>공식 400 ms 타이머 전</small>
    </div>
    <div class="recovery-score-bracket" aria-label="공식 400 ms 계측 구간">
      <span>공식 400 ms 계측 구간</span>
    </div>
    <div class="recovery-track">
      <div class="recovery-stage stage-port" data-recovery-stage="port">
        <span>② 선을 다시 잡음</span>
        <strong>80 ms</strong>
      </div>
      <div class="recovery-stage stage-data" data-recovery-stage="data">
        <span>③ 다음 쪽지를 기다림</span>
        <strong data-recovery-first-data>100 ms</strong>
      </div>
      <div class="recovery-stage stage-send" data-recovery-stage="send">
        <span>④ EdgeX로 전달</span>
        <strong>1 ms</strong>
      </div>
      <div class="recovery-stage stage-result" data-recovery-stage="result">
        <span>결과</span>
        <strong data-recovery-status>통과 예상</strong>
      </div>
    </div>
  </div>

  <div class="recovery-results">
    <div class="recovery-result official-result">
      <span>오류 감지 뒤 데이터 재개</span>
      <strong><output data-recovery-total>181 ms</output></strong>
      <small data-recovery-score>400 ms 내부 gate 통과 예상</small>
    </div>
    <div class="recovery-result">
      <span>사람이 체감할 수 있는 상한</span>
      <strong><output data-recovery-experience>581 ms</output></strong>
      <small>오류 발견 간격 + 공식 복구 구간</small>
    </div>
    <div class="recovery-result actual-result">
      <span>실제 30회 시험의 최대값</span>
      <strong>232.432 ms</strong>
      <small>현재 운영 구성, 30/30 통과</small>
    </div>
  </div>

  <p class="recovery-explain" data-recovery-explain aria-live="polite"></p>
  <p class="recovery-footnote">교실 모델은 port 준비 80 ms, Uno auto-reset 1,750 ms 또는 다음 sample 대기 최대 1회, EdgeX enqueue 1 ms를 사용합니다. 실제 판정은 Device Service의 phase metric과 30회 장애 주입 결과를 따릅니다.</p>
</section>"""


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

    def image(m: re.Match[str]) -> str:
        alt, url = m.group(1), html.unescape(m.group(2))
        if url.startswith("/home/") or url.startswith("/") and not url.startswith("//"):
            return stash(f'<code>{html.escape(url)}</code>')
        if not re.match(r"^(?:https?:)?//|^data:", url):
            source_asset = (current_md.parent / url).resolve()
            try:
                source_asset.relative_to(DOCS)
                url = rel_to_asset(current_html, source_asset)
            except ValueError:
                pass
        return stash(
            '<figure class="doc-figure">'
            f'<img src="{html.escape(url, quote=True)}" alt="{alt}" loading="lazy">'
            '</figure>'
        )

    s = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", image, s)

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
        if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", stripped):
            flush_para()
            out.append(inline_md(stripped, current_html, current_md))
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
      <button type=\"button\" data-search-filter=\"start\">시작하기</button>
      <button type=\"button\" data-search-filter=\"guide\">연결 가이드</button>
      <button type=\"button\" data-search-filter=\"ops\">운영</button>
      <button type=\"button\" data-search-filter=\"policy\">정책과 계약</button>
      <button type=\"button\" data-search-filter=\"reference\">개발 참고</button>
    </div>
    <input id=\"doc-search-input\" type=\"search\" placeholder=\"예: device status, dashboard, KPI, runbook\" autocomplete=\"off\">
    <div id=\"doc-search-results\" class=\"search-results\" aria-live=\"polite\"></div>
  </div>
  <script src=\"{html.escape(script_href, quote=True)}\" defer></script>
</section>"""


def home_intro_markup() -> str:
    return """<section class=\"home-intro\" aria-label=\"빠른 시작\">
  <a class=\"intro-card primary\" href=\"펌프-모터-이상감지-서비스.html\">
    <small>01 · SERVICE</small>
    <strong>현재 서비스 이해하기</strong>
    <span>이상감지 입력, 판단 결과와 알림 흐름을 설명합니다.</span>
  </a>
  <a class=\"intro-card\" href=\"ops/대시보드-배포.html\">
    <small>02 · DEPLOY</small>
    <strong>대시보드 배포하기</strong>
    <span>Git push, Argo CD, Traefik 검증 절차를 확인합니다.</span>
  </a>
  <a class=\"intro-card\" href=\"ops/현재-데모-운영-절차.html\">
    <small>03 · OPERATE</small>
    <strong>현재 데모 운영하기</strong>
    <span>EdgeX 수집부터 대시보드까지 운영 상태를 점검합니다.</span>
  </a>
  <a class=\"intro-card\" href=\"프로젝트-범위.html\">
    <small>04 · SCOPE</small>
    <strong>프로젝트 범위</strong>
    <span>현재 구현과 2차년도 목표, 레거시 경계를 구분합니다.</span>
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
    if rel in PUBLIC_META:
        return PUBLIC_META[rel][0]
    if rel.startswith("ops/"):
        return "운영"
    return "개발 참고"


def filter_of(rel: str) -> str:
    if rel in PUBLIC_META:
        return PUBLIC_META[rel][1]
    if rel.startswith("ops/"):
        return "ops"
    return "reference"


def is_search_excluded(rel: str) -> bool:
    return False


def archive_banner(rel: str) -> str:
    return f"""<aside class=\"archive-banner\" aria-label=\"보관 문서 안내\">
  <strong>과거 자료</strong>
  <span>현재 구축 목표가 아니라 과거 연구·통합·레거시 맥락 확인용입니다. 현재 판단은 최신 기준 문서를 우선하세요.</span>
  <code>{html.escape(rel)}</code>
</aside>"""


def history_banner(rel: str) -> str:
    return f"""<aside class=\"history-banner\" aria-label=\"설계 이력 안내\">
  <strong>설계 이력</strong>
  <span>현재 운영 기능의 완료 근거가 아닙니다. 계획·명세·실험 이력은 최신 기준 문서와 실제 코드·manifest·테스트를 함께 확인하세요.</span>
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
        current_attr = ' class="active" aria-current="page"' if target == current else ""
        chunks.append(f'<li><a{current_attr} href="{href}">{html.escape(title)}</a></li>')
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
    is_serial_recovery_explainer = rel == SERIAL_RECOVERY_EXPLAINER_PATH
    playground = serial_recovery_playground_markup() if is_serial_recovery_explainer else ""
    body = playground + render_markdown(text, out_path, md)
    interactive_script = (
        f'  <script src="{html.escape(rel_to_serial_recovery_explainer_js(out_path))}" defer></script>\n'
        if is_serial_recovery_explainer else ""
    )
    is_archive = rel.startswith("archive/")
    is_history = filter_of(rel) == "history"
    kind = group_of(rel)
    desc = short_desc(first_paragraph(text))
    page_class = "doc archive" if is_archive else "doc"
    archive_note = f"        {archive_banner(rel)}\n" if is_archive else ""
    history_note = f"        {history_banner(rel)}\n" if is_history else ""
    html_text = f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="{html.escape(rel_to_css(out_path))}">
</head>
<body>
  <div class="site-shell">
    <div class="topbar">
      <div class="topbar-left">
        <a class="docs-brand" href="{Path(os.path.relpath(OUT / 'index.html', out_path.parent)).as_posix()}"><span class="brand-mark">E</span><span>Edge AI Docs</span></a>
        <span class="section-label">{html.escape(kind)}</span>
      </div>
      <div class="topbar-actions">
        <span class="doc-path">{html.escape(rel)}</span>
        <a class="edit-link" href="/__edit?file={html.escape(rel, quote=True)}">편집</a>
      </div>
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
{archive_note}{history_note}        <div class="doc-body">
          {body}
        </div>
      </article>
      {toc_for(text)}
    </div>
  </div>
{interactive_script}
  <footer>Generated from docs/*.md</footer>
</body>
</html>
'''
    out_path.write_text(html_text, encoding="utf-8")


def render_index(files: list[Path]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    groups: dict[str, list[Path]] = {section: [] for section, _, _ in PUBLICATION_SECTIONS}
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
            href = Path(rel).with_suffix(".html").as_posix()
            cards.append(f'<li><a class="doc-card" href="{href}"><strong>{html.escape(title)}</strong><small>{html.escape(rel)}</small><span aria-hidden="true">→</span></a></li>')
        content = f'<div class="collection-head"><h2>{html.escape(name)}</h2><span>{len(group_files)}개 문서</span></div><ul class="card-grid">' + "\n".join(cards) + "</ul>"
        sections.append(f'<section class="doc-collection">{content}</section>')
    index = f'''<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Edge AI 플랫폼 문서</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="{html.escape(rel_to_css(OUT / 'index.html'))}">
</head>
<body>
  <nav class="home-nav" aria-label="문서 사이트">
    <a class="docs-brand" href="index.html"><span class="brand-mark">E</span><span>Edge AI Docs</span></a>
    <div>
      <span class="status-dot">운영 문서</span>
      <a href="/__edit">문서 편집</a>
    </div>
  </nav>
  <main class="home">
    <article class="home-card">
      <header class="home-hero-grid">
        <div class="home-hero">
          <p class="eyebrow">KUBEEDGE · EDGEX · GITOPS</p>
          <h1>Edge AI 플랫폼 문서</h1>
          <p class="subtitle">
            현장 디바이스 연결부터 AI 서비스 배포·검증까지, 지금 운영하는 구조만 설명합니다.
          </p>
          <a class="hero-link" href="플랫폼-개요.html">현재 아키텍처 보기 →</a>
        </div>
        <figure class="hero-visual">
          <img src="{html.escape(rel_to_asset(OUT / 'index.html', DOCS / 'assets' / 'images' / '플랫폼-개념-비주얼-v2.png'))}" alt="공장 설비와 엣지 컴퓨터, 중앙 플랫폼이 연결된 Edge AI 개념도">
        </figure>
      </header>
      <div class="section-kicker"><span>START HERE</span><h2>무엇을 하시나요?</h2></div>
      {home_intro_markup()}
      <div class="home-search">
        {search_box_markup("공개 문서 검색", rel_to_search_index(OUT / 'index.html'), rel_to_search_js(OUT / 'index.html'))}
      </div>
      <div class="home-body">
        <div class="section-kicker"><span>REFERENCE</span><h2>유지 관리 문서</h2><p>현재 코드와 배포 기준에 맞춘 {len(files)}개 문서만 공개합니다.</p></div>
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
    if OUT.exists():
        if OUT.resolve().parent != DOCS.resolve() or OUT.name != "html":
            raise RuntimeError(f"생성 디렉터리 안전 검증 실패: {OUT}")
        shutil.rmtree(OUT)
    render_index(files)
    render_search_index(files)
    for md in files:
        render_doc(md, files)
    print(f"generated {len(files)} docs into {OUT}")


if __name__ == "__main__":
    main()
