"""Reproduce a small supervised image classifier; no runtime training dependency."""
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import random
import urllib.request

ROOT = Path(__file__).resolve().parent
URL = "https://raw.githubusercontent.com/scikit-learn/scikit-learn/1.7.2/sklearn/datasets/data/digits.csv.gz"


def main():
    with urllib.request.urlopen(URL, timeout=30) as response:
        raw = response.read()
    if hashlib.sha256(raw).hexdigest() != "09f66e6debdee2cd2b5ae59e0d6abbb73fc2b0e0185d2e1957e9ebb51e23aa22":
        raise ValueError("pinned training dataset checksum mismatch")
    rows = [[float(v) for v in row] for row in csv.reader(io.StringIO(gzip.decompress(raw).decode()))]
    assert len(rows) == 1797 and all(len(row) == 65 for row in rows)
    train, test = [], []
    rng = random.Random(20260915)
    for label in range(10):
        values = [row for row in rows if row[-1] == label]
        rng.shuffle(values)
        cut = int(len(values) * .8)
        train.extend(values[:cut]); test.extend(values[cut:])
    centroids = []
    for label in range(10):
        values = [row[:64] for row in train if row[-1] == label]
        centroids.append([sum(row[i] for row in values) / len(values) for i in range(64)])
    model = {"algorithm": "supervised-nearest-centroid", "model_name": "digits-centroid",
             "shape": [1, 64], "pixelRange": [0, 16], "classes": list(range(10)), "centroids": centroids}
    encoded = (json.dumps(model, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (ROOT / "model.json").write_bytes(encoded)
    def predict(row):
        return min(range(10), key=lambda i: sum((v - c) ** 2 for v, c in zip(row[:64], centroids[i])))
    correct = sum(predict(row) == int(row[-1]) for row in test)
    fixture = next(row for row in test if int(row[-1]) == 7 and predict(row) == 7)
    (ROOT.parent / "examples/digits-model/input.json").write_text(json.dumps({"inputs": [
        {"name": "pixels", "datatype": "FP32", "shape": [1, 64], "data": fixture[:64]}]}, indent=2) + "\n")
    record = {"dataset": "scikit-learn digits / UCI Optical Recognition of Handwritten Digits",
        "datasetUrl": URL, "datasetSha256": hashlib.sha256(raw).hexdigest(), "seed": 20260915,
        "split": "stratified deterministic 80/20", "trainSamples": len(train), "testSamples": len(test),
        "correct": correct, "accuracy": correct / len(test), "modelSha256": hashlib.sha256(encoded).hexdigest(),
        "fixtureExpectedClass": 7, "fixturePurpose": "known-correct held-out smoke fixture; not a separate accuracy test",
        "scope": "execution interoperability demonstration, not an industrial inspection model"}
    (ROOT / "training.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
