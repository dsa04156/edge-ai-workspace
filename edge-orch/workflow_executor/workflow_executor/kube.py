from __future__ import annotations

from kubernetes import client, config


def build_batch_api() -> client.BatchV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.BatchV1Api()
