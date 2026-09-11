from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from patch_edgecore_config import ConfigurationError, patch_lines, validate_inputs


V123_CONFIG = """\
apiVersion: edgecore.config.kubeedge.io/v1alpha2
modules:
  edgeHub:
    httpServer: https://192.168.0.1:10002
    websocket:
      enable: true
      server: 192.168.0.1:10000
  edgeStream:
    enable: true
    server: 192.168.0.1:10004
  edged:
    hostnameOverride: old-edge
    tailoredKubeletConfig:
      containerRuntimeEndpoint: unix:///old.sock
      imageServiceEndpoint: unix:///old.sock
  metaManager:
    metaServer:
      enable: false
  serviceBus:
    enable: true
    server: 127.0.0.1
"""

LEGACY_CONFIG = """\
apiVersion: edgecore.config.kubeedge.io/v1alpha1
modules:
  edgeHub:
    httpServer: https://192.168.0.1:10002
    websocket:
      server: 192.168.0.1:10000
  edgeStream:
    server: 192.168.0.1:10004
  edged:
    hostnameOverride: old-edge
    remoteImageEndpoint: unix:///var/run/dockershim.sock
    remoteRuntimeEndpoint: unix:///var/run/dockershim.sock
    runtimeType: docker
  metaManager:
    metaServer:
      enable: false
"""


def test_patches_v123_edgecore_shape_without_touching_service_bus():
    config = V123_CONFIG.replace("  edgeStream:\n    enable: true", "  edgeStream:\n    enable: false")
    patched, changed = patch_lines(
        config.splitlines(keepends=True),
        "etri-dev0004-raspi5",
        "192.168.0.56",
        "unix:///run/containerd/containerd.sock",
    )
    result = "".join(patched)

    assert "hostnameOverride: etri-dev0004-raspi5" in result
    assert "httpServer: https://192.168.0.56:10002" in result
    assert "server: 192.168.0.56:10000" in result
    assert "server: 192.168.0.56:10004" in result
    assert "  edgeStream:\n    enable: true\n" in result
    assert result.count("unix:///run/containerd/containerd.sock") == 2
    assert "      clusterDNS:\n      - 169.254.96.16\n" in result
    assert "server: 127.0.0.1" in result
    assert "modules.metaManager.metaServer.enable" in changed
    assert "modules.edged.tailoredKubeletConfig.clusterDNS" in changed
    assert "modules.edgeStream.enable" in changed


def test_patch_is_idempotent():
    first, _ = patch_lines(
        V123_CONFIG.splitlines(keepends=True),
        "etri-dev0004-raspi5",
        "192.168.0.56",
        "unix:///run/containerd/containerd.sock",
    )
    second, changed = patch_lines(
        first,
        "etri-dev0004-raspi5",
        "192.168.0.56",
        "unix:///run/containerd/containerd.sock",
    )

    assert second == first
    assert changed == []


def test_preserves_existing_tailored_cluster_dns():
    config = V123_CONFIG.replace(
        "    tailoredKubeletConfig:\n",
        "    tailoredKubeletConfig:\n      clusterDNS:\n      - 10.96.0.10\n",
    )

    patched, changed = patch_lines(
        config.splitlines(keepends=True),
        "etri-dev0004-raspi5",
        "192.168.0.56",
        "unix:///run/containerd/containerd.sock",
    )
    result = "".join(patched)

    assert result.count("clusterDNS:") == 1
    assert "      - 10.96.0.10\n" in result
    assert "modules.edged.tailoredKubeletConfig.clusterDNS" not in changed


def test_patches_legacy_runtime_shape():
    patched, _ = patch_lines(
        LEGACY_CONFIG.splitlines(keepends=True),
        "etri-dev0004-jetorn",
        "192.168.0.56",
        "unix:///run/containerd/containerd.sock",
    )
    result = "".join(patched)

    assert result.count("unix:///run/containerd/containerd.sock") == 2
    assert "runtimeType: remote" in result
    assert "hostnameOverride: etri-dev0004-jetorn" in result


def test_accepts_tinker_edge_r_identity():
    validate_inputs("etri-dev0004-tedger", "tinker", "192.168.0.56")


def test_accepts_jetagx_identity():
    validate_inputs("etri-dev0005-jetagx", "jetagx", "192.168.0.56")


@pytest.mark.parametrize(
    ("node_name", "node_class"),
    [
        ("edge-4", "raspi"),
        ("etri-dev0004-jetorn", "raspi"),
        ("etri-dev0004-raspi5", "jetson"),
        ("etri-dev0004-tedger", "jetson"),
    ],
)
def test_rejects_invalid_or_mismatched_node_names(node_name, node_class):
    with pytest.raises(ConfigurationError):
        validate_inputs(node_name, node_class, "192.168.0.56")


def test_rejects_public_cloudcore_address_for_lan_onboarding():
    with pytest.raises(ConfigurationError):
        validate_inputs("etri-dev0004-raspi5", "raspi", "8.8.8.8")


def test_rejects_loopback_cloudcore_address_for_lan_onboarding():
    with pytest.raises(ConfigurationError):
        validate_inputs("etri-dev0004-raspi5", "raspi", "127.0.0.1")


def test_rejects_incompatible_generated_yaml_shape():
    incomplete = V123_CONFIG.replace("  edgeStream:\n", "  removedEdgeStream:\n")
    with pytest.raises(ConfigurationError, match="missing required paths"):
        patch_lines(
            incomplete.splitlines(keepends=True),
            "etri-dev0004-raspi5",
            "192.168.0.56",
            "unix:///run/containerd/containerd.sock",
        )
