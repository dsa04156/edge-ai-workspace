"""Bounded per-service/revision gateway observations; replay is never a new sample."""
from collections import deque
import math


class LatencyWindow:
    def __init__(self):
        self.samples = {}

    def record(self, uid, target, at, milliseconds, success):
        if not math.isfinite(milliseconds) or milliseconds < 0:
            return
        self.samples.setdefault((uid, target), deque(maxlen=2048)).append((at, milliseconds, success))

    def prune(self, now):
        for key, samples in list(self.samples.items()):
            while samples and (samples[0][0] < now - 600 or samples[0][0] > now):
                samples.popleft()
            if not samples:
                del self.samples[key]

    def observe(self, uid, target, now, policy, since=0):
        rows = [r for r in self.samples.get((uid, target), ())
                if max(since, now - policy.windowSeconds) <= r[0] <= now]
        successes = sorted(r[1] for r in rows if r[2])
        failures = len(rows) - len(successes)
        valid = len(successes) >= policy.minSamples and failures == 0
        return {"at": now, "target": target, "samples": len(rows), "successfulSamples": len(successes),
                "failures": failures, "p95Milliseconds": successes[math.ceil(.95 * len(successes)) - 1] if successes else None,
                "valid": valid, "reason": "recent_request_failure" if failures else "measured" if valid else "insufficient_samples",
                "windowSeconds": policy.windowSeconds, "maxP95Milliseconds": policy.maxP95Milliseconds,
                "returnP95Milliseconds": policy.returnP95Milliseconds,
                "scope": "gateway_queue_and_worker_response", "processLocal": True}
