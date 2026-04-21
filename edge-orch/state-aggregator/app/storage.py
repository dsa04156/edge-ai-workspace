from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from .models import NodeState, WorkflowEvent, WorkflowState


class StateStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.node_log = self.data_dir / "node_state.jsonl"
        self.workflow_log = self.data_dir / "workflow_event.jsonl"
        self.nodes: dict[str, NodeState] = {}
        self.workflows: dict[str, WorkflowState] = {}
        self._lock = Lock()

    def upsert_node_state(self, node_state: NodeState) -> None:
        with self._lock:
            self.nodes[node_state.hostname] = node_state
            self._append_jsonl(self.node_log, node_state.model_dump(mode="json"))

    def record_workflow_event(self, event: WorkflowEvent, workflow_state: WorkflowState) -> None:
        with self._lock:
            self.workflows[workflow_state.workflow_id] = workflow_state
            self._append_jsonl(self.workflow_log, event.model_dump(mode="json"))

    def get_node_states(self) -> list[NodeState]:
        with self._lock:
            return list(self.nodes.values())

    def get_workflow_states(self) -> list[WorkflowState]:
        with self._lock:
            return list(self.workflows.values())

    @staticmethod
    def _append_jsonl(path: Path, payload: dict) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")
