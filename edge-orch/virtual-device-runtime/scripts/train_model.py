"""Reproduce learned parameters; sklearn is used only by this offline builder."""
import json
from pathlib import Path
import numpy as np
from sklearn.datasets import load_iris
from sklearn.model_selection import train_test_split

data = load_iris()
x_train, x_test, y_train, y_test = train_test_split(
    data.data, data.target, test_size=0.2, stratify=data.target, random_state=42)
centroids = np.array([x_train[y_train == index].mean(axis=0) for index in range(3)])
predicted = np.linalg.norm(x_test[:, None] - centroids[None, :], axis=2).argmin(axis=1)
artifact = {
    "algorithm": "nearest-centroid-v1", "modelId": "iris-centroid", "version": "1.0.0",
    "labels": data.target_names.tolist(), "features": data.feature_names,
    "centroids": centroids.tolist(),
    "training": {"dataset": "sklearn.datasets.load_iris (Fisher Iris)",
                 "source": "https://archive.ics.uci.edu/dataset/53/iris",
                 "sklearn": "1.7.1", "seed": 42, "trainCount": len(x_train),
                 "testCount": len(x_test), "heldOutAccuracy": float((predicted == y_test).mean()),
                 "note": "Toy classifier; no factory quality or anomaly qualification."},
}
target = Path(__file__).resolve().parents[1] / "models/iris-centroids.json"
target.write_text(json.dumps(artifact, indent=2) + "\n")
print(json.dumps(artifact["training"], indent=2))
