from app.reconciler import RuntimeReconciler

from fakes import FakeEdgeXServiceProbe, FakeKubernetesGateway
from test_renderer import deployable_template, runtime_cr


def test_reconciler_applies_owned_resources_and_reports_deploying():
    kube = FakeKubernetesGateway(deployment_ready=False)
    probe = FakeEdgeXServiceProbe(ready=False)
    reconciler = RuntimeReconciler(
        kube=kube,
        edgex_probe=probe,
        namespace="edgex-edge",
    )

    status = reconciler.reconcile(runtime_cr(), deployable_template())

    assert [item["kind"] for item in kube.applied] == [
        "ConfigMap",
        "Deployment",
        "Service",
        "NetworkPolicy",
    ]
    assert status["phase"] == "DEPLOYING"
    assert status["managementMode"] == "controller"
    assert status["observedGeneration"] == 1
    assert probe.calls == []
    assert kube.statuses[-1][1]["phase"] == "DEPLOYING"


def test_reconciler_requires_edgex_service_readback_for_service_ready():
    kube = FakeKubernetesGateway(deployment_ready=True)
    probe = FakeEdgeXServiceProbe(ready=False)
    reconciler = RuntimeReconciler(kube, probe, namespace="edgex-edge")

    workload_status = reconciler.reconcile(runtime_cr(), deployable_template())
    assert workload_status["phase"] == "WORKLOAD_READY"
    assert probe.calls == ["adapter-serial-managed-abc123"]

    probe.ready = True
    service_status = reconciler.reconcile(runtime_cr(), deployable_template())
    assert service_status["phase"] == "SERVICE_READY"
    assert service_status["edgeXServiceObserved"] is True


def test_reconciler_preserves_transition_time_and_skips_unchanged_status_patch():
    resource = runtime_cr()
    kube = FakeKubernetesGateway(deployment_ready=True)
    probe = FakeEdgeXServiceProbe(ready=True)
    reconciler = RuntimeReconciler(kube, probe, namespace="edgex-edge")

    first = reconciler.reconcile(resource, deployable_template())
    resource["status"] = first
    second = reconciler.reconcile(resource, deployable_template())

    assert second["lastTransitionTime"] == first["lastTransitionTime"]
    assert len(kube.statuses) == 1


def test_reconciler_retires_only_exact_owner_resources():
    resource = runtime_cr()
    resource["spec"]["desiredState"] = "Retired"
    resource["status"] = {"consumers": 0}
    kube = FakeKubernetesGateway(deployment_ready=True)
    probe = FakeEdgeXServiceProbe(ready=True)
    reconciler = RuntimeReconciler(kube, probe, namespace="edgex-edge")

    status = reconciler.reconcile(resource, deployable_template())

    assert kube.applied == []
    assert kube.deleted == [
        ("Deployment", "adapter-serial-managed-abc123"),
        ("Service", "adapter-serial-managed-abc123"),
        ("ConfigMap", "adapter-serial-managed-abc123"),
        ("NetworkPolicy", "adapter-serial-managed-abc123"),
    ]
    assert status["phase"] == "RETIRED"


def test_reconciler_does_not_retire_runtime_with_consumers():
    resource = runtime_cr()
    resource["spec"]["desiredState"] = "Retired"
    resource["status"] = {"consumers": 2}
    kube = FakeKubernetesGateway()
    reconciler = RuntimeReconciler(
        kube,
        FakeEdgeXServiceProbe(),
        namespace="edgex-edge",
    )

    status = reconciler.reconcile(resource, deployable_template())

    assert kube.deleted == []
    assert status["phase"] == "FAILED"
    assert status["lastError"]["code"] == "runtime_has_consumers"


def test_reconciler_rechecks_edgex_consumers_at_the_delete_boundary():
    resource = runtime_cr()
    resource["spec"]["desiredState"] = "Retired"
    resource["status"] = {"consumers": 0}
    kube = FakeKubernetesGateway()
    probe = FakeEdgeXServiceProbe(consumers=1)
    reconciler = RuntimeReconciler(
        kube,
        probe,
        namespace="edgex-edge",
    )

    status = reconciler.reconcile(resource, deployable_template())

    assert probe.consumer_calls == ["adapter-serial-managed-abc123"]
    assert kube.deleted == []
    assert status["phase"] == "FAILED"
    assert status["consumers"] == 1
    assert status["lastError"]["code"] == "runtime_has_consumers"
