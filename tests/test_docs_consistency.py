import unittest
from pathlib import Path

from tools.docs_consistency.rules import Corpus, rule_core_data_event_origin


class CoreDataEventOriginRuleTest(unittest.TestCase):
    def corpus(self, text: str) -> Corpus:
        return Corpus(root=Path("."), docs={"docs/example.md": text}, code={})

    def test_ignores_docs_that_do_not_claim_telemetry_freshness(self):
        result = rule_core_data_event_origin(
            self.corpus("EdgeX Core Metadata에서 Device inventory를 조회한다.")
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])

    def test_warns_when_core_data_freshness_omits_event_origin(self):
        result = rule_core_data_event_origin(
            self.corpus("EdgeX Core Data latest Event로 telemetry freshness를 판단한다.")
        )

        self.assertEqual(result.status, "WARN")
        self.assertEqual(len(result.findings), 1)

    def test_accepts_core_data_event_origin_as_freshness_clock(self):
        result = rule_core_data_event_origin(
            self.corpus(
                "EdgeX Core Data latest Event의 nanosecond `origin`을 sample 시각으로 사용해 "
                "telemetry freshness를 판단한다. API 조회 시각으로 대체하지 않는다."
            )
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])

    def test_one_clock_definition_covers_later_summary_claims_in_same_doc(self):
        result = rule_core_data_event_origin(
            self.corpus(
                "EdgeX Core Data latest Event의 nanosecond `origin`을 sample 시각으로 사용해 "
                "telemetry freshness를 판단한다.\n\n"
                "| KPI | 의미 |\n"
                "|---|---|\n"
                "| freshness | Core Data latest Event가 fresh인 Device 수 |"
            )
        )

        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.findings, [])


if __name__ == "__main__":
    unittest.main()
