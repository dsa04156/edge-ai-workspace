"""Package canonical schemas/examples for the existing dashboard Docker context."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT.parent / "edge-orch/state-aggregator/app/config/profile_spec_v1.json"


def bundle():
    return {
        "apiVersion": "edgeai.etri/v1",
        "maturity": "draft",
        "schemas": {p.name.split(".")[0]: json.loads(p.read_text())
                    for p in sorted((ROOT / "schemas").glob("*.json"))},
        "examples": {p.stem: json.loads(p.read_text())
                     for p in sorted((ROOT / "examples").glob("*.json"))},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(bundle(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != content:
            raise SystemExit("Profile bundle is stale: run python3 profile-spec/build_bundle.py")
        print("Profile bundle matches canonical schemas and examples")
    else:
        TARGET.write_text(content)
        print(TARGET)
