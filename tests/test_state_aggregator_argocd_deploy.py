from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docker-build-push.yml"
DEPLOYMENT = ROOT / "edge-orch" / "state-aggregator" / "k8s" / "deployment.yaml"
ARGO_APPS = ROOT / "edge-orch-argocd" / "argocd-apps.yaml"


def test_state_aggregator_build_exports_immutable_digest() -> None:
    workflow = WORKFLOW.read_text()

    assert "--metadata-file /tmp/state-aggregator-build-metadata.json" in workflow
    assert 'DIGEST=$(jq -r \'."containerimage.digest"\'' in workflow
    assert (
        'echo "STATE_AGGREGATOR_IMAGE=${{ env.REGISTRY }}/state-aggregator@${DIGEST}"'
        in workflow
    )


def test_state_aggregator_deploy_is_owned_by_argocd() -> None:
    workflow = WORKFLOW.read_text()

    assert "Deploy state-aggregator image through Argo CD" in workflow
    assert "kubectl patch application edge-orch-state-aggregator -n argocd" in workflow
    assert 'targetRevision\\\":\\\"${TARGET_REVISION}' in workflow
    assert 'kustomize\\\":{\\\"images\\\":[\\\"${STATE_AGGREGATOR_IMAGE}' in workflow
    assert "argocd.argoproj.io/refresh=hard" in workflow
    assert 'test "${CURRENT_IMAGE}" = "${STATE_AGGREGATOR_IMAGE}"' in workflow
    assert "kubectl set image deployment/state-aggregator" not in workflow
    assert "state-aggregator-dashboard-screen-css" not in workflow


def test_state_aggregator_gitops_baseline_is_immutable_and_self_healing() -> None:
    deployment = DEPLOYMENT.read_text()
    applications = ARGO_APPS.read_text()

    assert "image: 192.168.0.56:5000/state-aggregator@sha256:" in deployment
    assert "image: 192.168.0.56:5000/state-aggregator:latest" not in deployment
    assert "name: edge-orch-state-aggregator" in applications
    assert "path: edge-orch/state-aggregator/k8s" in applications
    assert "automated:" in applications
    assert "selfHeal: true" in applications
