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
        self.assertEqual(readme["group"], "최신 기준 문서")
        self.assertEqual(readme["filter"], "active")
        self.assertIn("서비스 데모", readme["text"])
        self.assertIn("디바이스 상태", readme["text"])
        self.assertNotIn("```", readme["text"])
        ops = next(item for item in data if item["path"] == "ops/운영-절차.md")
        archive = next(item for item in data if item["path"] == "archive/과거-연구.md")
        detail_log = next(item for item in data if item["path"] == "archive/integration/통합-상세-기록.md")
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
        self.assertIn('data-search-filter="history"', html)
        self.assertIn('data-search-filter="archive"', html)
        self.assertIn('docs-search.js', html)

    def test_home_intro_prioritizes_current_scope(self):
        intro = build_docs_html.home_intro_markup()
        self.assertIn("AI 서비스 연결하기", intro)
        self.assertIn("대시보드 배포하기", intro)
        self.assertIn("현재 데모 운영하기", intro)
        self.assertIn("프로젝트 범위", intro)

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
        self.assertIn("edge workload | `device-serial-jetson`, `device-sensehat-raspi` 각 1 replica", runbook)
        self.assertIn("`edgex-edge-agent-*`", runbook)
        self.assertIn("고정 ClusterIP, PodIP와 node IP를 설정에 넣거나 우회 경로로 사용하지 않는다", runbook)
        self.assertIn("device-serial-jetson.edgex-edge.svc.cluster.local", runbook)
        self.assertIn("device-sensehat-raspi.edgex-edge.svc.cluster.local", runbook)
        self.assertIn("/dev/arduino-001", runbook)
        self.assertIn("/dev/i2c-1", runbook)
        self.assertIn("공유 Serial reader 1개", runbook)
        self.assertIn("Device/resource별 최근 10분·최대 10,000 sample", runbook)
        self.assertIn("/api/v3/localdata/device/name/", runbook)
        self.assertIn("edge-ai.io/local-data-client=true", runbook)
        self.assertIn("Flannel", runbook)
        self.assertIn("보안 경계가 아니다", runbook)
        self.assertIn("SQLite outbox/offline replay: 없음", runbook)
        self.assertIn("InfluxDB workload를 배포하지 않는다", runbook)
        for device_name in (
            "virtual-temperature-001",
            "virtual-light-001",
            "virtual-magnetic-001",
            "virtual-acceleration-x-001",
            "virtual-acceleration-y-001",
            "virtual-acceleration-z-001",
            "env-sensehat-temperature-01",
            "env-sensehat-humidity-01",
            "env-sensehat-pressure-01",
            "imu-sensehat-compass-01",
            "imu-sensehat-orientation-01",
            "imu-sensehat-gyroscope-01",
        ):
            self.assertIn(device_name, runbook)

    def test_network_runbook_records_cloud_only_edgemesh_service_filters(self):
        runbook = (ROOT / "docs" / "ops" / "네트워크-문제해결.md").read_text(encoding="utf-8")

        self.assertIn("service.edgemesh.kubeedge.io/service-proxy-name", runbook)
        self.assertIn("kube-dns", runbook)
        self.assertIn("argocd-repo-server", runbook)
        self.assertIn("argocd-redis", runbook)
        self.assertIn("edgex-ingest-gateway", runbook)


if __name__ == "__main__":
    unittest.main()
