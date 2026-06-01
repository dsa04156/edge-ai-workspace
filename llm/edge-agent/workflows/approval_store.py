from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


class ApprovalStore:
    """In-memory human-in-the-loop approval store.

    Initial version intentionally does not execute approved plans. A production
    deployment should replace this with persistent storage and a separate,
    policy-controlled executor.
    """

    def __init__(self) -> None:
        self._plans: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def create_plan(self, message: str, plan: dict[str, Any]) -> dict[str, Any]:
        plan_id = str(uuid4())
        record = {
            "plan_id": plan_id,
            "message": message,
            "plan": plan,
            "status": "pending_approval",
            "approval_required": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "approved_at": None,
        }
        with self._lock:
            self._plans[plan_id] = record
        return record

    def approve_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._plans.get(plan_id)
            if record is None:
                return None
            record["status"] = "approved_not_executed"
            record["approved_at"] = datetime.now(timezone.utc).isoformat()
            return dict(record)

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._plans.get(plan_id)
            return dict(record) if record else None
