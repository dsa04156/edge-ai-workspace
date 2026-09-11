from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Protocol


class ModelAdapter(Protocol):
    model_id: str
    version: str
    digest: str

    def infer(self, features: list[float]) -> dict: ...


class NearestCentroid:
    """Euclidean nearest class centroid learned from Iris training data.

    Distances are model outputs, NOT probabilities or calibrated confidence.
    Runtime has no sklearn dependency and never trains or downloads a model.
    """

    def __init__(self, path: Path):
        raw = path.read_bytes()
        data = json.loads(raw)
        if data["algorithm"] != "nearest-centroid-v1":
            raise ValueError("unsupported model algorithm")
        self.model_id, self.version = data["modelId"], data["version"]
        self.digest = hashlib.sha256(raw).hexdigest()
        self.labels, self.centroids = data["labels"], data["centroids"]
        if not self.model_id or not self.version or len(self.labels) != 3 or len(set(self.labels)) != 3:
            raise ValueError("invalid model identity/classes")
        if len(self.centroids) != 3 or any(
            len(row) != 4 or any(type(x) not in (int, float) or not math.isfinite(x) for x in row)
            for row in self.centroids
        ):
            raise ValueError("invalid centroid dimensions/values")

    def infer(self, features: list[float]) -> dict:
        distances = [math.dist(features, centroid) for centroid in self.centroids]
        index = min(range(len(distances)), key=distances.__getitem__)
        return {"label": self.labels[index], "classIndex": index,
                "distances": dict(zip(self.labels, distances)), "units": "euclidean_cm"}


def load_adapter(backend: str, path: Path) -> ModelAdapter:
    if backend != "nearest-centroid":
        raise ValueError(f"unsupported model adapter: {backend}")
    return NearestCentroid(path)
