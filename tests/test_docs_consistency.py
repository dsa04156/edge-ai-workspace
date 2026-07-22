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


if __name__ == "__main__":
    unittest.main()
