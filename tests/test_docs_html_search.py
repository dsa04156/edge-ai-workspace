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
            (docs / "문서-안내.md").write_text(
                "# 문서 안내\n\n서비스 데모와 디바이스 상태를 설명한다.\n\n```bash\necho secret\n```\n",
                encoding="utf-8",
            )
            (docs / "ops").mkdir()
            (docs / "ops" / "운영-절차.md").write_text(
                "# 현재 데모 운영 절차\n\n장애 조치와 대시보드 확인 절차.\n",
                encoding="utf-8",
            )
            (docs / "archive").mkdir()
            (docs / "archive" / "과거-연구.md").write_text(
                "# 과거 연구\n\n선택적 재계획 과거 기록.\n",
                encoding="utf-8",
            )
            (docs / "archive" / "integration").mkdir()
            (docs / "archive" / "integration" / "통합-상세-기록.md").write_text(
                "# 통합 상세 기록\n\n아주 긴 과거 통합 기록.\n",
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
        readme = next(item for item in data if item["path"] == "문서-안내.md")
        self.assertEqual(readme["title"], "문서 안내")
        self.assertEqual(readme["url"], "문서-안내.html")
        self.assertEqual(readme["group"], "시작하기")
        self.assertEqual(readme["filter"], "start")
        self.assertIn("서비스 데모", readme["text"])
        self.assertIn("디바이스 상태", readme["text"])
        self.assertNotIn("```", readme["text"])
        ops = next(item for item in data if item["path"] == "ops/운영-절차.md")
        self.assertEqual(ops["filter"], "ops")

    def test_index_page_exposes_search_ui(self):
        html = build_docs_html.search_box_markup("문서 검색", "search-index.json")
        self.assertIn('id="doc-search-input"', html)
        self.assertIn('data-search-index="search-index.json"', html)
        self.assertIn('id="doc-search-results"', html)
        self.assertIn('data-search-filter="all"', html)
        self.assertIn('data-search-filter="start"', html)
        self.assertIn('data-search-filter="guide"', html)
        self.assertIn('data-search-filter="ops"', html)
        self.assertIn('data-search-filter="policy"', html)
        self.assertIn('data-search-filter="reference"', html)
        self.assertIn('docs-search.js', html)

    def test_publication_set_contains_only_current_maintained_docs(self):
        files = build_docs_html.md_files()
        paths = [path.relative_to(ROOT / "docs").as_posix() for path in files]

        self.assertEqual(len(paths), 18)
        self.assertIn("처음부터-배우는-Edge-AI-시스템.md", paths)
        self.assertEqual(paths, build_docs_html.PUBLIC_PATHS)
        self.assertIn("플랫폼-개요.md", paths)
        self.assertIn("펌프-모터-이상감지-서비스.md", paths)
        self.assertIn("AI-서비스-자원-증강-부하-실험.md", paths)
        self.assertNotIn("일일-기록.md", paths)
        self.assertFalse(any(path.startswith(("archive/", "superpowers/", "wiki/")) for path in paths))

    def test_home_intro_prioritizes_current_scope(self):
        intro = build_docs_html.home_intro_markup()
        self.assertIn("현재 서비스 이해하기", intro)
        self.assertIn("펌프-모터-이상감지-서비스.html", intro)
        self.assertIn("대시보드 배포하기", intro)
        self.assertIn("현재 데모 운영하기", intro)
        self.assertIn("프로젝트 범위", intro)

    def test_current_service_document_explains_the_observed_anomaly_contract(self):
        guide = (ROOT / "docs" / "펌프-모터-이상감지-서비스.md").read_text(encoding="utf-8")

        for required in (
            "현재 모델은 옥동 설비에서 학습한 고장 분류 AI가 아니라",
            "`online-baseline`",
            "RMS",
            "kurtosis",
            "결과 이력",
            "알림 이력",
            "Server1 전환 경계",
        ):
            self.assertIn(required, guide)

    def test_sidebar_marks_current_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp) / "docs"
            out = docs / "html"
            docs.mkdir()
            first = docs / "문서-안내.md"
            second = docs / "프로젝트-범위.md"
            first.write_text("# 문서 안내\n", encoding="utf-8")
            second.write_text("# 프로젝트 범위\n", encoding="utf-8")
            old_docs, old_out = build_docs_html.DOCS, build_docs_html.OUT
            try:
                build_docs_html.DOCS = docs
                build_docs_html.OUT = out
                markup = build_docs_html.sidebar([first, second], out / "문서-안내.html")
            finally:
                build_docs_html.DOCS = old_docs
                build_docs_html.OUT = old_out

        self.assertEqual(markup.count('aria-current="page"'), 1)
        self.assertIn('class="active" aria-current="page" href="문서-안내.html"', markup)

    def test_archive_banner_warns_not_current_direction(self):
        banner = build_docs_html.archive_banner("archive/integration/통합-문서.md")
        self.assertIn("과거 자료", banner)
        self.assertIn("현재 구축 목표", banner)
        self.assertIn("archive/integration/통합-문서.md", banner)

    def test_display_titles_are_korean_and_descriptions_are_short(self):
        self.assertEqual(build_docs_html.display_title("서비스-데모-시나리오.md", "# Service Demo Scenario\n"), "서비스 데모 시나리오")
        self.assertEqual(build_docs_html.display_title("archive/integration/통합-문서.md", "# 통합문서\n"), "통합 문서")
        self.assertEqual(build_docs_html.display_title("archive/integration/통합-상세-기록.md", "# 통합 문서\n"), "통합 상세 기록")
        long = "이 문서는 현재 구현 기준으로 아래 2가지를 한 번에 설명한다. 비용모델과 런타임 orchestration이 어떤 구성으로 어떻게 동작하는지 아주 길게 설명한다."
        self.assertLessEqual(len(build_docs_html.short_desc(long)), 80)

    def test_operational_runbook_records_current_serial_and_i2c_device_service_boundary(self):
        runbook = (ROOT / "docs" / "ops" / "현재-데모-운영-절차.md").read_text(encoding="utf-8")

        self.assertNotIn("ssl.create_default_context", runbook)
        self.assertNotIn("load_cert_chain", runbook)
        self.assertIn("`device-serial-jetson`", runbook)
        self.assertIn("`device-sensehat-raspi`", runbook)
        self.assertIn("`edgex-edge-agent-*`", runbook)
        self.assertIn("고정 ClusterIP, PodIP와 node IP를 설정에 넣거나 우회 경로로 사용하지 않는다", runbook)
        self.assertIn("/dev/arduino-001", runbook)
        self.assertIn("/dev/i2c-1", runbook)
        self.assertIn("nanosecond `origin`", runbook)
        self.assertIn("sensor-anomaly-demo", runbook)
        self.assertIn("설비 anomaly", runbook)
        self.assertIn("latency/backlog", runbook)

    def test_network_runbook_records_cloud_only_edgemesh_service_filters(self):
        runbook = (ROOT / "docs" / "ops" / "네트워크-문제해결.md").read_text(encoding="utf-8")

        self.assertIn("service.edgemesh.kubeedge.io/service-proxy-name", runbook)
        self.assertIn("kube-dns", runbook)
        self.assertIn("argocd-repo-server", runbook)
        self.assertIn("argocd-redis", runbook)
        self.assertIn("edgex-ingest-gateway", runbook)


if __name__ == "__main__":
    unittest.main()
