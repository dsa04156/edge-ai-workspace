"""stdlib-only client. A successful exit verifies request/result/status identity."""
import argparse
import hashlib
import json
import uuid
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--client-id", default="etri-dev0001-jetorn", help="Declared client ID, not attested host identity")
parser.add_argument("--request-id", default=None)
parser.add_argument("--features", nargs=4, type=float, default=[5.1, 3.5, 1.4, 0.2])
parser.add_argument("--expected-label", default=None)
parser.add_argument("--expected-model", default="iris-centroid")
parser.add_argument("--expected-version", default="1.0.0")
args = parser.parse_args()

def call(path, body=None):
    raw = json.dumps(body).encode() if body is not None else None
    with urlopen(Request(args.url.rstrip("/") + path, data=raw,
                         headers={"Content-Type": "application/json"}), timeout=10) as response:
        return json.load(response)

ready = call("/readyz")
assert ready["ready"] is True, ready
before = call("/status")
request = {"requestId": args.request_id or str(uuid.uuid4()), "clientId": args.client_id, "features": args.features}
result = call("/infer", request)
after = call("/status")
assert result["requestId"] == request["requestId"] and result["clientId"] == args.client_id
assert result["virtualDeviceId"] == after["virtualDeviceId"] == "vd-demo-001"
assert result["model"]["id"] == args.expected_model and result["model"]["version"] == args.expected_version
assert result["inputSha256"] == hashlib.sha256(json.dumps(args.features, separators=(",", ":")).encode()).hexdigest()
assert before["bootId"] == after["bootId"] == result["bootId"], "process replaced during test"
assert before["podUid"] == after["podUid"] == result["podUid"]
assert after["succeeded"] == before["succeeded"] + 1, "run this evidence check without concurrent clients"
assert after["lastSuccess"] == result, "last result does not match response"
assert after["inFlight"] == 0 and after["modelReady"] is True
if args.expected_label:
    assert result["result"]["label"] == args.expected_label
print(json.dumps({"request": request, "response": result,
                  "beforeSucceeded": before["succeeded"], "afterSucceeded": after["succeeded"],
                  "statusMatched": True}, ensure_ascii=False, indent=2))
