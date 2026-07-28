from __future__ import annotations

from .device_discovery_models import (
    CandidateDecommissionUpdate,
    CandidateDecisionUpdate,
    CandidateDeleteRequest,
    CandidateMutationRef,
    CandidateView,
    DiscoveryInventory,
    ManualCandidateCreate,
    ManualCandidateInput,
)


class DeviceDiscoveryManagementService:
    def __init__(self, controller) -> None:
        self.controller = controller

    async def list_inventory(self) -> DiscoveryInventory:
        return await self.controller.list_discovery_inventory()

    async def create_manual(
        self,
        candidate: ManualCandidateInput,
        request_ref: CandidateMutationRef,
    ) -> CandidateView:
        return await self.controller.create_manual_candidate(
            ManualCandidateCreate(
                candidate=candidate,
                request_ref=request_ref,
            )
        )

    async def update_decision(
        self,
        candidate_id: str,
        request: CandidateDecisionUpdate,
    ) -> CandidateView:
        return await self.controller.update_candidate_decision(
            candidate_id,
            request,
        )

    async def delete_candidate(
        self,
        candidate_id: str,
        request_ref: CandidateMutationRef,
    ) -> CandidateView:
        return await self.controller.delete_candidate(
            candidate_id,
            CandidateDeleteRequest(request_ref=request_ref),
        )

    async def decommission_candidate(
        self,
        candidate_id: str,
        *,
        reason: str,
        actor: str,
        request_ref: CandidateMutationRef,
    ) -> CandidateView:
        return await self.controller.decommission_candidate(
            candidate_id,
            CandidateDecommissionUpdate(
                actor=actor,
                reason=reason,
                request_ref=request_ref,
            ),
        )
