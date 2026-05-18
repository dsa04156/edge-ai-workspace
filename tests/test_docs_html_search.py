import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-docs-html.py"

spec = importlib.util.spec_from_file_location("build_docs_html", SCRIPT)
build_docs_html = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_docs_html)


class DocsHtmlSearchTest(unittest.TestCase):
    def test_build_search_index_contains_doc_metadata_and_plain_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            out = docs / "html"
            docs.mkdir()
            (docs / "README.md").write_text(
                "# 운영 문서\n\n서비스 데모와 디바이스 상태를 설명한다.\n\n```bash\necho secret\n```\n",
                encoding="utf-8",
            )
            (docs / "ops").mkdir()
            (docs / "ops" / "runbook.md").write_text(
                "# 현재 데모 Runbook\n\n장애 조치와 dashboard 확인 절차.\n",
                encoding="utf-8",
            )
            (docs / "archive").mkdir()
            (docs / "archive" / "old.md").write_text(
                "# 과거 연구\n\nselective replanning 과거 기록.\n",
                encoding="utf-8",
            )
            (docs / "archive" / "integration").mkdir()
            (docs / "archive" / "integration" / "integration-detail-log.md").write_text(
                "# 통합 상세 로그\n\n아주 긴 과거 통합 로그.\n",
                encoding="utf-8",
            )

            old_docs, old_out = build_docs_html.DOCS, build_docs_html.OUT
            try:
                build_docs_html.DOCS = docs
                build_docs_html.OUT = out
                files = build_docs_html.md_files()
                build_docs_html.render_search_index(files)
                index_path = out / "search-index.json"
                self.assertTrue(index_path.exists())
                data = json.loads(index_path.read_text(encoding="utf-8"))
            finally:
                build_docs_html.DOCS = old_docs
                build_docs_html.OUT = old_out

        self.assertEqual(len(data), 4)
        readme = next(item for item in data if item["path"] == "README.md")
        self.assertEqual(readme["title"], "문서 안내")
        self.assertEqual(readme["url"], "README.html")
        self.assertEqual(readme["group"], "Active 문서")
        self.assertEqual(readme["filter"], "active")
        self.assertIn("서비스 데모", readme["text"])
        self.assertIn("디바이스 상태", readme["text"])
        self.assertNotIn("```", readme["text"])
        ops = next(item for item in data if item["path"] == "ops/runbook.md")
        archive = next(item for item in data if item["path"] == "archive/old.md")
        detail_log = next(item for item in data if item["path"] == "archive/integration/integration-detail-log.md")
        self.assertEqual(ops["filter"], "ops")
        self.assertEqual(archive["filter"], "archive")
        self.assertFalse(archive["search_excluded"])
        self.assertTrue(detail_log["search_excluded"])
        self.assertEqual(detail_log["filter"], "archive")

    def test_index_page_exposes_search_ui(self):
        html = build_docs_html.search_box_markup("문서 검색", "search-index.json")
        self.assertIn('id="doc-search-input"', html)
        self.assertIn('data-search-index="search-index.json"', html)
        self.assertIn('id="doc-search-results"', html)
        self.assertIn('data-search-filter="all"', html)
        self.assertIn('data-search-filter="active"', html)
        self.assertIn('data-search-filter="ops"', html)
        self.assertIn('data-search-filter="archive"', html)
        self.assertIn('docs-search.js', html)

    def test_home_intro_marks_archive_as_secondary(self):
        intro = build_docs_html.home_intro_markup()
        self.assertIn("시스템 구축 목표", intro)
        self.assertIn("Active와 운영 문서를 먼저", intro)
        self.assertIn("Archive는 과거 맥락", intro)

    def test_archive_banner_warns_not_current_direction(self):
        banner = build_docs_html.archive_banner("archive/integration/integration-doc.md")
        self.assertIn("과거 자료", banner)
        self.assertIn("현재 구축 목표", banner)
        self.assertIn("archive/integration/integration-doc.md", banner)

    def test_display_titles_are_korean_and_descriptions_are_short(self):
        self.assertEqual(build_docs_html.display_title("service-demo-scenario.md", "# Service Demo Scenario\n"), "서비스 데모 시나리오")
        self.assertEqual(build_docs_html.display_title("archive/integration/integration-doc.md", "# 통합문서\n"), "통합 문서")
        self.assertEqual(build_docs_html.display_title("archive/integration/integration-detail-log.md", "# 통합문서\n"), "통합 상세 로그")
        long = "이 문서는 현재 구현 기준으로 아래 2가지를 한 번에 설명한다. 비용모델과 런타임 orchestration이 어떤 구성으로 어떻게 동작하는지 아주 길게 설명한다."
        self.assertLessEqual(len(build_docs_html.short_desc(long)), 80)


if __name__ == "__main__":
    unittest.main()
