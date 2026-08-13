import unittest
from pathlib import Path

from tools.docs_consistency.rules import Corpus, rule_core_data_event_origin

ROOT = Path(__file__).resolve().parents[1]


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


class CurrentDeviceManagementScopeTest(unittest.TestCase):
    def test_current_docs_define_bounded_edgex_device_management_scope(self):
        scope = (ROOT / "docs/프로젝트-범위.md").read_text(encoding="utf-8")

        self.assertIn("edgex-adapter-controller", scope)
        self.assertIn("ADAPTER_RUNTIME_MUTATION_ENABLED", scope)
        self.assertIn("Controller가 만든 `AdapterRuntime`", scope)
        self.assertIn("임의 image", scope)
        self.assertIn("고정\n  ClusterIP/PodIP", scope)
        self.assertIn("Modbus, OPC-UA, MQTT와 RTSP", scope)
        self.assertIn("Workflow Builder", scope)


class DashboardDeploymentGuideTest(unittest.TestCase):
    def test_guide_documents_gitops_image_and_traefik_completion_gates(self):
        guide = (ROOT / "docs/ops/대시보드-배포.md").read_text(encoding="utf-8")

        for required in (
            "edge-orch/state-aggregator/k8s/ingressroute.yaml",
            "edge-orch-state-aggregator",
            "agent/edgex-central-docs",
            "immutable digest",
            "docker-build-push.yml",
            "aggregator.192.168.0.56.sslip.io",
            "Synced",
            "Healthy",
            "git revert",
        ):
            self.assertIn(required, guide)

        self.assertIn("브랜치 push만으로는", guide)
        self.assertIn("kubectl set image", guide)


class SecondYearOkdongPlanTest(unittest.TestCase):
    def test_report_body_stays_concise_and_separates_technical_appendices(self):
        plan = (ROOT / "docs/단계별-추진계획.md").read_text(encoding="utf-8")

        self.assertTrue(
            plan.startswith("# 2026년도 2차년도 옥동 PoC 추진계획(안)\n")
        )
        self.assertLessEqual(len(plan.splitlines()), 140)
        for section in (
            "## 1. 추진 배경",
            "## 2. 추진 목표",
            "## 3. 주요 추진내용",
            "## 4. 월별 추진계획",
            "## 5. 기관별 역할",
            "## 6. 주요 산출물",
            "## 7. 최종 추진 방향",
        ):
            self.assertIn(section, plan)
        for required in (
            "2026년 7월 29일 옥동 현장회의",
            "센서·MES 데이터 기반 생산품질 양품·불량 판별",
            "메인·보조 유압펌프 및 모터 이상 감지",
            "[현재 데모 운영 절차](ops/현재-데모-운영-절차.md)",
            "[대시보드 정보 구조](대시보드-정보-구조.md)",
            "현재 구현 완료\n> 상태를 뜻하지 않는다",
        ):
            self.assertIn(required, plan)
        for technical_detail in (
            "AdapterRuntime",
            "EVENT_CONFIRMED",
            "online-gaussian-baseline",
            "Runtime Resource Augmentation Scheduler",
        ):
            self.assertNotIn(technical_detail, plan)


if __name__ == "__main__":
    unittest.main()
