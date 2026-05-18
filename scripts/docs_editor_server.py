#!/usr/bin/env python3
"""Small local Markdown editor for the generated docs HTML site.

This intentionally has no auth and is meant for trusted LAN/local use only.
It edits existing docs/*.md files, then regenerates docs/html via build-docs-html.py.
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
BUILD_SCRIPT = ROOT / "scripts" / "build-docs-html.py"


def resolve_doc_path(docs_root: Path, rel_path: str) -> Path:
    docs_root = docs_root.resolve()
    rel_path = unquote(rel_path).lstrip("/")
    if not rel_path.endswith(".md"):
        raise ValueError("only .md files under docs can be edited")
    target = (docs_root / rel_path).resolve()
    try:
        target.relative_to(docs_root)
    except ValueError as exc:
        raise ValueError("path must stay under docs") from exc
    if not target.exists() or not target.is_file():
        raise ValueError("target markdown file does not exist")
    return target


def save_markdown(docs_root: Path, rel_path: str, content: str) -> str:
    target = resolve_doc_path(docs_root, rel_path)
    target.write_text(content, encoding="utf-8")
    return target.read_text(encoding="utf-8")


def list_markdown_files(docs_root: Path) -> list[str]:
    return sorted(
        p.relative_to(docs_root).as_posix()
        for p in docs_root.rglob("*.md")
        if "/html/" not in p.as_posix()
    )


def run_build() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(BUILD_SCRIPT)],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


class DocsEditorHandler(SimpleHTTPRequestHandler):
    docs_root = DOCS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print("[docs-editor] " + format % args)

    def send_text(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, status: int, payload: dict) -> None:
        self.send_text(status, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/__edit":
            qs = parse_qs(parsed.query)
            rel = qs.get("file", [""])[0]
            self.serve_editor(rel)
            return
        if parsed.path == "/__api/doc":
            qs = parse_qs(parsed.query)
            rel = qs.get("file", [""])[0]
            try:
                target = resolve_doc_path(self.docs_root, rel)
            except ValueError as exc:
                self.send_json(400, {"ok": False, "error": str(exc)})
                return
            self.send_json(200, {"ok": True, "file": rel, "content": target.read_text(encoding="utf-8")})
            return
        if parsed.path == "/__api/list":
            self.send_json(200, {"ok": True, "files": list_markdown_files(self.docs_root)})
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/__api/save":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            rel = payload.get("file", "")
            content = payload.get("content", "")
            saved = save_markdown(self.docs_root, rel, content)
            build = run_build()
            if build.returncode != 0:
                self.send_json(500, {"ok": False, "file": rel, "saved": True, "error": build.stderr, "stdout": build.stdout})
                return
            self.send_json(200, {"ok": True, "file": rel, "bytes": len(saved.encode("utf-8")), "build": build.stdout.strip()})
        except Exception as exc:
            self.send_json(400, {"ok": False, "error": str(exc)})

    def serve_editor(self, rel: str) -> None:
        options = "\n".join(
            f'<option value="{html.escape(path)}" {"selected" if path == rel else ""}>{html.escape(path)}</option>'
            for path in list_markdown_files(self.docs_root)
        )
        body = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>문서 편집</title>
  <style>
    :root {{ --bg:#eef2f7; --paper:#fff; --ink:#111827; --muted:#667085; --line:#d8dee9; --accent:#1d4ed8; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font-family:ui-sans-serif,system-ui,"Noto Sans KR",sans-serif; }}
    main {{ width:min(1200px, calc(100% - 32px)); margin:24px auto; }}
    header, .editor {{ background:var(--paper); border:1px solid var(--line); border-radius:20px; box-shadow:0 18px 48px rgba(15,23,42,.08); }}
    header {{ padding:24px 28px; margin-bottom:16px; }}
    h1 {{ margin:0 0 8px; font-size:32px; letter-spacing:-.04em; }}
    p {{ margin:0; color:var(--muted); }}
    .bar {{ display:flex; gap:10px; align-items:center; padding:14px; border-bottom:1px solid var(--line); flex-wrap:wrap; }}
    select {{ min-width:360px; min-height:42px; padding:0 12px; border:1px solid var(--line); border-radius:12px; }}
    button, a.button {{ min-height:42px; padding:9px 14px; border:0; border-radius:12px; background:var(--accent); color:white; font-weight:800; text-decoration:none; cursor:pointer; }}
    button.secondary, a.secondary {{ background:#f8fafc; color:var(--ink); border:1px solid var(--line); }}
    textarea {{ width:100%; min-height:66vh; padding:18px; border:0; outline:0; resize:vertical; font:14px/1.6 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
    .status {{ padding:12px 16px; border-top:1px solid var(--line); color:var(--muted); white-space:pre-wrap; }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>Markdown 문서 편집</h1>
      <p>기존 docs/*.md 파일을 수정하고 저장하면 HTML 문서 사이트를 자동 재생성한다. trusted local/LAN 용도다.</p>
    </header>
    <section class="editor">
      <div class="bar">
        <select id="file">{options}</select>
        <button id="load" class="secondary">불러오기</button>
        <button id="save">저장 + HTML 재생성</button>
        <a id="view" class="button secondary" href="/html/index.html" target="_blank">HTML 보기</a>
      </div>
      <textarea id="content" spellcheck="false"></textarea>
      <div id="status" class="status">대기 중</div>
    </section>
  </main>
  <script>
    const file = document.getElementById('file');
    const content = document.getElementById('content');
    const status = document.getElementById('status');
    const view = document.getElementById('view');
    function htmlPath(md) {{ return '/html/' + md.replace(/\\.md$/, '.html'); }}
    async function loadDoc() {{
      const rel = file.value;
      const res = await fetch('/__api/doc?file=' + encodeURIComponent(rel));
      const data = await res.json();
      if (!data.ok) throw new Error(data.error);
      content.value = data.content;
      view.href = htmlPath(rel);
      history.replaceState(null, '', '/__edit?file=' + encodeURIComponent(rel));
      status.textContent = '불러옴: ' + rel;
    }}
    async function saveDoc() {{
      const rel = file.value;
      status.textContent = '저장 중...';
      const res = await fetch('/__api/save', {{
        method: 'POST',
        headers: {{'Content-Type':'application/json'}},
        body: JSON.stringify({{file: rel, content: content.value}})
      }});
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || JSON.stringify(data));
      status.textContent = '저장 완료: ' + rel + '\\n' + data.build;
      view.href = htmlPath(rel);
    }}
    document.getElementById('load').onclick = () => loadDoc().catch(e => status.textContent = '오류: ' + e.message);
    document.getElementById('save').onclick = () => saveDoc().catch(e => status.textContent = '오류: ' + e.message);
    file.onchange = () => loadDoc().catch(e => status.textContent = '오류: ' + e.message);
    if (file.value) loadDoc().catch(e => status.textContent = '오류: ' + e.message);
  </script>
</body>
</html>"""
        self.send_text(200, body, "text/html; charset=utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DocsEditorHandler)
    print(f"Docs editor serving on http://{args.host}:{args.port}/html/index.html")
    print(f"Editor: http://{args.host}:{args.port}/__edit")
    server.serve_forever()


if __name__ == "__main__":
    main()
