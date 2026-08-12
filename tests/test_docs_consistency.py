import unittest
from pathlib import Path

from tools.docs_consistency.rules import Corpus, rule_influx_timestamp_notes


class InfluxTimestampRuleTest(unittest.TestCase):
    def corpus(self, text: str) -> Corpus:
        return Corpus(root=Path("."), docs={"docs/example.md": text}, code={})

    def test_ignores_docs_that_do_not_describe_influx_timestamp_semantics(self):
        result = rule_influx_timestamp_notes(
            self.corpus("EdgeX Core Data latest Event로 telemetry freshness를 판단한다.")
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])

    def test_does_not_treat_latest_event_timestamp_as_flux_time_column(self):
        result = rule_influx_timestamp_notes(
            self.corpus("EdgeX `latest_event_timestamp`로 telemetry freshness를 판단한다.")
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])

    def test_ignores_influx_legacy_path_without_latest_claim(self):
        result = rule_influx_timestamp_notes(
            self.corpus("mapper가 InfluxDB로 직접 쓰는 경로는 legacy다.")
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])

    def test_warns_when_influx_latest_claim_omits_timestamp_semantics(self):
        result = rule_influx_timestamp_notes(
            self.corpus("InfluxDB latest telemetry를 dashboard freshness에 사용한다.")
        )

        self.assertEqual(result.status, "WARN")
        self.assertEqual(len(result.findings), 1)

    def test_accepts_complete_influx_timestamp_semantics(self):
        result = rule_influx_timestamp_notes(
            self.corpus(
                "InfluxDB latest telemetry에서 `_start`와 `_stop`은 Flux query window이고, "
                "`_time`은 실제 sample timestamp다. device-level latest sample 기준이며 "
                "property별 freshness를 보장하지 않는다."
            )
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])


class DocumentClassificationTest(unittest.TestCase):
    root = Path(__file__).resolve().parents[1]
    docs = root / "docs"

    def test_archive_sources_have_current_scope_guard(self):
        files = sorted((self.docs / "archive").rglob("*.md"))
        self.assertTrue(files)
        for path in files:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:12])
            self.assertIn("상태:", head, path.as_posix())
            self.assertIn("현재 PoC", head, path.as_posix())

    def test_design_history_sources_have_status(self):
        paths = sorted((self.docs / "superpowers").rglob("*.md"))
        paths.extend(
            self.docs / name
            for name in (
                "대시보드-화면-설계.md",
                "일일-기록.md",
                "자원-증강-가상디바이스-대시보드.md",
                "런타임-자원-증강-데모-워크플로.md",
            )
        )
        for path in paths:
            head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:14])
            self.assertIn("상태:", head, path.as_posix())
            self.assertIn("설계 이력", head, path.as_posix())

    def test_document_inventory_is_linked_from_entry_points(self):
        inventory = self.docs / "문서-분류-목록.md"
        self.assertTrue(inventory.exists())
        for name in ("문서-안내.md", "문서-정리-계획.md", "프로젝트-범위.md", "저장소-구조.md"):
            text = (self.docs / name).read_text(encoding="utf-8")
            self.assertIn("문서-분류-목록.md", text, name)


if __name__ == "__main__":
    unittest.main()
