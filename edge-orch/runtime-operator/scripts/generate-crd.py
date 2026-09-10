#!/usr/bin/env python3
"""Generate the structural CRD from the same contract validated by the operator."""
import copy
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime_operator.contract import ServiceSpec


def structural(schema, definitions):
    schema = copy.deepcopy(schema)
    if "$ref" in schema:
        referenced = definitions[schema.pop("$ref").split("/")[-1]]
        schema = {**referenced, **schema}
    schema.pop("title", None)
    schema.pop("$defs", None)
    if "const" in schema:
        schema["enum"] = [schema.pop("const")]
    for key, limit in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
        if key in schema and not isinstance(schema[key], bool):
            schema[limit] = schema[key]
            schema[key] = True
    if "anyOf" in schema and any(s == {"type": "null"} for s in schema["anyOf"]):
        choices = [s for s in schema.pop("anyOf") if s != {"type": "null"}]
        if len(choices) != 1:
            raise ValueError("unsupported nullable union")
        schema.update(choices[0])
        schema["nullable"] = True
        return structural(schema, definitions)
    # Kubernetes structural schemas prune unknown fields. The runtime validator
    # additionally rejects unknown values when called directly.
    if schema.get("additionalProperties") is False:
        schema.pop("additionalProperties")
    for key in ("properties",):
        if key in schema:
            schema[key] = {k: structural(v, definitions) for k, v in schema[key].items()}
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), dict):
            schema[key] = structural(schema[key], definitions)
    return schema


def generate():
    model = ServiceSpec.model_json_schema()
    spec = structural(model, model.get("$defs", {}))
    return {"apiVersion": "apiextensions.k8s.io/v1", "kind": "CustomResourceDefinition", "metadata": {
        "name": "runtimeservices.platform.jinuk.io"}, "spec": {"group": "platform.jinuk.io", "scope": "Namespaced",
        "names": {"plural": "runtimeservices", "singular": "runtimeservice", "kind": "RuntimeService", "shortNames": ["rtsvc"]},
        "versions": [{"name": "v1alpha1", "served": True, "storage": True, "subresources": {"status": {}},
            "additionalPrinterColumns": [{"name": "Phase", "type": "string", "jsonPath": ".status.phase"},
                                         {"name": "Node", "type": "string", "jsonPath": ".status.active.node"}],
            "schema": {"openAPIV3Schema": {"type": "object", "required": ["spec"], "properties": {
                "apiVersion": {"type": "string"}, "kind": {"type": "string"}, "metadata": {"type": "object"},
                "spec": spec, "status": {"type": "object", "x-kubernetes-preserve-unknown-fields": True}}}}}]}}


if __name__ == "__main__":
    (ROOT / "k8s/crd.yaml").write_text(yaml.safe_dump(generate(), sort_keys=False))
