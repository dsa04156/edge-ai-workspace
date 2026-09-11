# Skill Observation Log

Observations captured during task-oriented work.

**Status key:** OPEN = not yet actioned | ACTIONED (YYYY-MM-DD) = skill
updated/created | DECLINED (YYYY-MM-DD) = user decided not to pursue —
resolved statuses always carry their resolution date

---

## 2026-08-20

### Observation 1: Validate indirection behind advertised build commands

**Status:** OPEN
**Date:** 2026-08-20
**Session context:** Repository-wide generation of scoped AGENTS.md files from real build and test evidence.
**Skill:** wiki-agents-md
**Type:** open-source
**Phase/Area:** Command discovery and validation
**Reference file:** `mappers/mapper-framework/_template/mapper/hack/make-rules/mapper.sh`

**Issue:** A Makefile help block advertised a test action, but its delegated shell rule invoked an undefined function. A template module also had relative replacements intended for its generated destination, so a direct in-place test command would be misleading.

**Suggested improvement:** In Step 3 and Step 6, require following dynamic/delegated Make targets into their implementation and checking whether commands are valid in the current folder or only after generation. Do not document help text alone as executable evidence.

**Principle:** Validate the complete command path and execution context; an advertised target is not proof that the command is implemented or runnable where it is documented.

### Observation 2: Do not generate tool-specific companion files without user demand

**Status:** OPEN
**Date:** 2026-08-20
**Session context:** User requested removal of generated CLAUDE.md files and correction of wiki-agents-md because Claude is not part of their workflow.
**Skill:** wiki-agents-md
**Type:** open-source
**Phase/Area:** Output scope and companion artifacts
**Reference file:** `/home/jinuk/.codex/skills/wiki-agents-md/SKILL.md`

**Issue:** The skill unconditionally generated a companion file for a separate coding product whenever it created AGENTS.md. That expanded the requested repository context work into an unrelated tool integration and left unwanted files behind.

**Suggested improvement:** Keep AGENTS.md generation product-neutral. Generate tool-specific redirect or companion files only when the user explicitly requests that integration.

**Principle:** Do not add configuration artifacts for products the user did not choose; companion integrations are opt-in scope, not a universal default.

### Observation 3: Separate portable skill source from machine-local runtime state

**Status:** OPEN
**Date:** 2026-08-20
**Session context:** Auditing an installed Codex skill environment for reuse across computers through Git.
**Skill:** New skill candidate: codex-environment-portability
**Type:** open-source
**Phase/Area:** Inventory, packaging, and bootstrap design

**Issue:** A local skill tree can mix small reusable instructions with large virtual environments, vendored dependencies, generated caches, hard-coded home paths, and machine-local authentication or session state. Copying the whole tree makes the repository unnecessarily large and can leak or preserve unusable state.

**Suggested improvement:** Define a portability workflow that classifies repo-scoped skills, personal authored skills, third-party installed skills, declarative configuration, and runtime state separately. Version authored source and a source/ref manifest, exclude generated dependencies and credentials, template machine-specific paths, and validate a clean bootstrap on a second location.

**Principle:** Portable agent environments should version reproducible intent and source provenance, while regenerating dependencies and keeping credentials, caches, sessions, and absolute machine paths outside Git.

### Observation 4: Validate skill metadata against the destination host

**Status:** OPEN
**Date:** 2026-08-20
**Session context:** Packaging an existing mixed-origin skill collection for installation on another Codex computer.
**Skill:** New skill candidate: codex-environment-portability
**Type:** open-source
**Phase/Area:** Compatibility validation

**Issue:** Several otherwise usable skills carried top-level frontmatter keys accepted by their source ecosystem but rejected by the current Codex skill validator. Copying the directories without destination validation would preserve a bundle that may not load consistently on another machine.

**Suggested improvement:** Run the destination host's validator against every packaged skill before publishing. Preserve useful unsupported metadata by nesting it under the host-supported `metadata` field instead of discarding provenance, version, compatibility, or invocation hints.

**Principle:** Portability requires validating against the destination schema, not merely reproducing the source files; adapt metadata losslessly whenever the host's accepted schema differs.

### Observation 5: Bound negative repository-history claims to the searched evidence

**Status:** OPEN
**Date:** 2026-08-24
**Session context:** Recovering evidence of a user-recalled DQN and LLM Kubernetes scheduling experiment from multiple local workspaces.
**Skill:** New skill candidate: repository-history-forensics
**Type:** open-source
**Phase/Area:** Evidence scope and negative findings

**Issue:** A working-tree and reachable Git-history search was described as proving that an experiment had never existed. The user's correction led to reflog, unreachable-object, neighboring-workspace, and coding-session checks, which located the experiment in a different local repository.

**Suggested improvement:** Define a forensic history workflow that scopes negative claims explicitly and checks the working tree, refs, reflogs, stashes, unreachable commits and blobs, archived documents, coding-session provenance, and neighboring repositories before concluding absence.

**Principle:** Report "not found in the searched evidence set," not "never existed," unless every plausible storage and history channel has been examined.

<!-- 2026-08-24 plan checkpoint: no observations -->

## 2026-08-25

### Observation 6: Separate scheduling headroom from live utilization

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Implementing a Kubernetes scheduling resource API that combines node capacity, Pod reservations, and Prometheus observations.
**Skill:** New skill candidate: Kubernetes scheduling resource read models
**Type:** open-source
**Phase/Area:** Resource semantics and API contract
**Reference file:** `edge-orch/state-aggregator/app/resource_pool.py`

**Issue:** A single “available resource” value can incorrectly mix Kubernetes scheduling reservations with live utilization. Kubernetes places Pods against allocatable capacity and requests, while Prometheus describes current pressure; substituting one for the other produces unstable or unschedulable placement decisions.

**Suggested improvement:** Define a reusable workflow that calculates allocatable minus non-terminal Pod requests, handles init containers and Pod overhead, keeps exact units and source provenance, and exposes Prometheus utilization as a separate observation with fail-closed readiness reasons.

**Principle:** Capacity, reservations, and utilization are different signals with different authorities; preserve each one explicitly before deriving placement eligibility.

### Observation 7: Distinguish transport acknowledgement from durable persistence

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Designing durable store-and-forward for a device framework whose asynchronous publish API does not return the downstream storage result.
**Skill:** New skill candidate: reliable edge delivery design
**Type:** open-source
**Phase/Area:** Delivery semantics and idempotency
**Reference file:** `docs/장애-저장-재전송-시스템-설계.md`

**Issue:** A broker publish success or later polling by timestamps can be mistaken for a persisted acknowledgement. When the producer does not know the generated event ID, timeout-and-retry creates a duplicate race and cannot support a strong deduplication claim.

**Suggested improvement:** Before choosing an outbox integration point, trace where stable identity is created and where durable storage is confirmed. Require a deterministic event ID, payload conflict hash, durable local admission, and an exact persisted acknowledgement from a component that can reconcile uncertain writes.

**Principle:** Reliable delivery requires identity and acknowledgement to span the same persistence boundary; transport acceptance alone is not evidence of durable, idempotent storage.

### Observation 8: Separate hard placement constraints from ranking signals

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Implementing a read-only node suitability evaluator over service requests and Kubernetes resource snapshots.
**Skill:** New skill candidate: explainable placement evaluation
**Type:** open-source
**Phase/Area:** Filtering, scoring, and decision explainability
**Reference file:** `edge-orch/state-aggregator/app/placement.py`

**Issue:** Folding hard requirements and preference signals into one score can allow an incompatible node to outrank a compatible one, while returning only a winner hides why other nodes were excluded or ranked lower.

**Suggested improvement:** Define placement as two explicit phases: first reject nodes on schedulability, capacity, architecture, accelerator, and observation completeness with stable reason codes; then score only eligible nodes using named, normalized components and deterministic tie-breaking. Return every candidate's eligibility, reasons, score inputs, and post-placement headroom.

**Principle:** Eligibility is a gate and scoring is a preference; keep them separate so no score can compensate for a violated requirement and every decision remains explainable.

### Observation 9: Narrow authority when promoting decisions into actuators

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Promoting a read-only Kubernetes placement decision into a controller that creates new workloads.
**Skill:** New skill candidate: safe decision-to-controller promotion
**Type:** open-source
**Phase/Area:** Mutation boundary, authorization, and deployment verification
**Reference file:** `edge-orch/state-aggregator/app/deployment_controller.py`

**Issue:** Reusing a trusted read model does not make its mutation path safe by itself. A generic manifest or image API, cluster-wide write role, or update semantics would turn a bounded placement decision into broad code-execution and workload-ownership authority.

**Suggested improvement:** Keep the decision phase pure and place mutation behind a distinct controller with a fixed namespace, create-only RBAC, immutable artifact allowlist, narrow typed inputs, authentication, explicit no-update behavior, condition-based readiness observation, and stable failure reason codes. Verify both the created specification and the resulting runtime state.

**Principle:** When a system crosses from recommendation to action, reduce authority at every boundary and require runtime evidence; trusted input does not justify a broad actuator.

### Observation 10: Make multi-command verification fail on the first error

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Verifying a Kubernetes controller with manifest rendering, tests, and diff checks in one shell invocation.
**Skill:** `verification-before-completion`
**Type:** open-source
**Phase/Area:** Command execution and exit-code integrity

**Issue:** A combined shell command reported a successful overall exit even though an early Kustomize render had failed, because a later diff check succeeded and supplied the final process status. The visible error was easy to notice interactively but unsafe as machine-consumed completion evidence.

**Suggested improvement:** Run independent completion proofs as separate tool calls, or use `set -euo pipefail` and explicit assertions so every failing sub-check propagates. Label each result and preserve its exit code instead of trusting only the final command in a chain.

**Principle:** Verification evidence is valid only when every required sub-check can independently fail the enclosing workflow.

### Observation 11: Persist timer anchors, not only visible decision states

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Generalizing a runtime recommendation state machine with hysteresis, dwell, cooldown, and restart survival.
**Skill:** New skill candidate: durable runtime recommendation engines
**Type:** open-source
**Phase/Area:** Stateful decision persistence and history
**Reference file:** `edge-orch/state-aggregator/app/runtime_recommendation.py`

**Issue:** Persisting only the latest label such as OBSERVING or RECOMMENDED cannot reconstruct how long a pressure, failure, recovery, or cooldown condition has lasted after a process restart. Rebuilding timers from the restart time silently changes decisions and makes history disagree with the actual observation window.

**Suggested improvement:** Persist each latch and its entry/recovery timestamp, the last recommendation timestamp, the latest typed decision, and a deduplicated transition history in one transactional store. Rehydrate these timer anchors before every evaluation and test a restart between dwell entry and completion.

**Principle:** Durable temporal decisions require durable time anchors and transition evidence; a persisted state label alone is not a persisted state machine.

### Observation 12: Do not treat cumulative counters as active failure signals

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Validating Kubernetes Pod failure signals in a persistent runtime recommendation state machine.
**Skill:** New skill candidate: durable runtime recommendation engines
**Type:** open-source
**Phase/Area:** Runtime signal semantics and recovery
**Reference file:** `edge-orch/state-aggregator/app/runtime_recommendation.py`

**Issue:** Kubernetes container `restartCount` is cumulative for the life of a Pod. Comparing the absolute total to a threshold as an independent current-failure condition keeps a recovered, Ready Pod in failure dwell forever and can repeatedly recommend replacement.

**Suggested improvement:** Treat current readiness, waiting/terminated reasons, and controller conditions as active failure signals. If restart frequency matters, persist a baseline and evaluate a time-bounded counter delta rather than the lifetime total; retain the total only as historical evidence.

**Principle:** Monotonic totals describe history, not present health; active decisions need current state or a bounded rate derived from durable baselines.

<!-- 2026-08-25 plan completion checkpoint: Observation 12 captured; no additional observations. -->

### Observation 13: Separate forward steps from conditional compensation

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Converting a runtime recommendation into a read-only execution plan with a rollback description.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Plan semantics and failure recovery
**Reference file:** `edge-orch/state-aggregator/app/runtime_execution_plan.py`

**Issue:** Listing rollback as an ordinary final step makes a plan look as though it should undo every successful replacement. It also hides which preceding failures trigger compensation and which artifacts must remain available for recovery.

**Suggested improvement:** Give every step an execution mode and dependencies. Keep the forward path ordered, mark rollback as `on_failure`, and attach explicit rollback triggers, retained-state prerequisites, restoration failures, and the current/candidate targets it compensates.

**Principle:** Compensation belongs to the failure graph, not the happy-path sequence; make its trigger, dependencies, retained state, and targets explicit even when presenting one ordered plan.

<!-- 2026-08-25 execution-plan task completion checkpoint: Observation 13 captured; no additional observations. -->

### Observation 14: Treat idempotency reservation as a recovery commitment

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Building an approval-gated execution controller that can create an external workload exactly once.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Idempotency, crash recovery, and external side effects
**Reference file:** `edge-orch/state-aggregator/app/runtime_execution_controller.py`

**Issue:** A process can stop after atomically reserving an idempotency key but before changing the record from PENDING to RUNNING, or after the external create succeeds but before success is persisted. Replaying either ambiguous record can duplicate an external side effect.

**Suggested improvement:** Reserve the key transactionally before mutation, treat both PENDING and RUNNING as possibly side-effecting after restart, and recover them to a manual-review BLOCKED state. Return the original record on duplicate requests and require reconciliation rather than automatic replay.

**Principle:** Once an idempotency key is durably reserved for an external mutation, ambiguous progress must fail closed; recovery should reconcile evidence, not repeat the command.

<!-- 2026-08-25 execution-controller plan completion checkpoint: Observation 14 captured; no additional observations. -->

### Observation 15: Reject source configuration that a bounded executor cannot preserve

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Building a narrow candidate Deployment executor from a richer live source workload.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Preflight contract fidelity
**Reference file:** `edge-orch/state-aggregator/app/runtime_execution_controller.py`

**Issue:** A restricted executor may accept a source workload but rebuild only its image and resources, silently dropping environment, commands, initialization, or storage configuration. The resulting object can pass admission while no longer representing the approved service.

**Suggested improvement:** Define the executable source subset explicitly, inspect the source before mutation, and fail preflight with a stable unsupported-contract reason whenever required fields cannot be reproduced. Never interpret omission as permission to discard semantics.

**Principle:** A bounded executor must preserve every accepted semantic input; anything it cannot faithfully represent belongs in a fail-closed preflight result, not in a lossy transformation.

### Observation 16: Treat static dashboard assertions as information-architecture contracts

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Adding a read-only service operations page while preserving the current overview, inventory, management, service-demo, and designer behavior.
**Skill:** `interface-design`
**Type:** open-source
**Phase/Area:** UI information architecture and regression testing
**Reference file:** `edge-orch/state-aggregator/tests/test_sensor_device_inventory.js`

**Issue:** Existing static HTML tests can encode an earlier navigation hierarchy and page ownership, such as requiring a service demo to live under a removed menu. A deliberate information-architecture change then fails regression even when the underlying feature remains present and functional.

**Suggested improvement:** When page ownership changes, update the navigation array, DOM `data-page` contract, and the affected static assertions together. Keep the assertions focused on preserved behavior and the newly approved hierarchy, while separately asserting that retired controls or panels remain absent.

**Principle:** Static UI tests are product contracts, not immutable markup snapshots; evolve them with approved information architecture while retaining explicit negative regression checks.

<!-- 2026-08-25 runtime-operations plan checkpoint: Observation 16 captured. -->

<!-- 2026-08-25 state-aggregator deployment checkpoint: no additional observations. -->

<!-- 2026-08-25 state-aggregator live-verification checkpoint: no additional observations. -->

### Observation 17: Separate approved candidate intent from observed source state

**Status:** OPEN
**Date:** 2026-08-25
**Session context:** Replacing source Deployment cloning with a Git-approved candidate workload contract.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Candidate templates, preflight, and state isolation
**Reference file:** `edge-orch/state-aggregator/app/candidate_workload_template.py`

**Issue:** Cloning a live source workload turns whatever is currently deployed—including drift, mutable defaults, and node-local storage bindings—into implicitly approved candidate intent. A cross-node candidate can then inherit unsafe PVCs or join the source Service selector before those effects are reviewed.

**Suggested improvement:** Keep the candidate specification in a versioned, immutable-image Git contract. Compare the observed source, storage, Service selector, and target Node against that contract during a read-only preflight, then materialize only the approved template with candidate-specific identity and an explicit state policy.

**Principle:** Observation can prove compatibility, but it must not define intent; executable candidate intent belongs in a reviewed contract with fail-closed state and traffic boundaries.

<!-- 2026-08-25 candidate-template plan checkpoint: Observation 17 captured. -->

<!-- 2026-08-25 candidate-template implementation and verification checkpoint: no additional observations. -->

### Observation 18: Inject time and transport into dwell-based validators

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Adding functional candidate validation with polling, timeout, and a continuous healthy dwell period.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Runtime validation and deterministic testing
**Reference file:** `edge-orch/state-aggregator/app/candidate_validation.py`

**Issue:** A controller test that reaches a real dwell loop can wait for the full production timeout and still cannot deterministically reproduce transient success followed by failure. Retrofitting fake time only in outer controller tests obscures whether the stability logic itself is correct.

**Suggested improvement:** Make wall-clock time, monotonic time, sleep, and HTTP transport explicit validation-engine seams. Test dwell and timeout rules directly with a fake clock and mock transport, then use a small stub engine only for controller sequencing and persistence tests.

**Principle:** Time-dependent safety gates need deterministic time and transport seams at the engine boundary; otherwise tests either become slow or stop proving the temporal policy.

<!-- 2026-08-26 candidate-validation implementation and verification checkpoint: Observation 18 captured. -->

### Observation 19: Verify every service-routing consumer before enabling a new endpoint API

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Designing selectorless Service routing with controller-owned EndpointSlices in a mixed Kubernetes/KubeEdge cluster.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Traffic routing compatibility and fail-closed preflight
**Reference file:** `edge-orch/state-aggregator/app/traffic_routing.py`

**Issue:** Kubernetes may support custom EndpointSlices while an edge data-plane proxy still watches only the legacy Endpoints API. Treating API-server acceptance as end-to-end routing compatibility can produce a successful-looking cutover that cloud kube-proxy observes but edge traffic does not.

**Suggested improvement:** Inventory every Service routing consumer, its watched resource types, RBAC, and deployed version. Keep the Git routing contract blocked until all traffic origins are proven to consume the chosen routing object, and gate mutation on selector, object ownership, and expected current state.

**Principle:** A routing API is operationally supported only when every active data-plane consumer is proven compatible, not merely when the control plane accepts the object.

<!-- 2026-08-26 traffic-routing plan checkpoint: Observation 19 captured. -->

<!-- 2026-08-26 traffic-routing implementation and verification checkpoint: no additional observations. -->

<!-- 2026-08-26 EdgeMesh live Endpoints routing proof checkpoint: no additional observations; Observation 19 already captures the consumer-level compatibility requirement. -->

### Observation 20: Fence the side effect, not only the work loop

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Adding Lease-based ACTIVE/SHADOW execution ownership to a polling and inference service.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Lease handoff and split-brain prevention
**Reference file:** `edge-orch/sensor-anomaly-demo/app/execution_ownership.py`

**Issue:** Checking a Lease only before a long polling or inference cycle can still allow the old owner to commit a result after ownership changed while that cycle was in flight. A single holder in the control-plane object does not by itself fence already-running work.

**Suggested improvement:** Revalidate and CAS-renew the exact holder immediately before every production side effect, keep SHADOW observations in memory, and require one replica with non-overlapping rollout semantics for every workload identity. Treat API errors, conflicts and expired Leases as loss of execution authority.

**Principle:** Distributed ownership must fence the irreversible commit boundary; gating only task admission leaves a split-brain window for in-flight work.

<!-- 2026-08-26 Lease ownership implementation and verification checkpoint: Observation 20 captured; no additional observations. -->

### Observation 21: Prove the workload-to-control-plane path before adopting Lease gating

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Deploying Lease-gated processing to an edge workload through GitOps.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Edge control-plane connectivity preflight
**Reference file:** `edge-orch/sensor-anomaly-demo/app/execution_ownership.py`

**Issue:** An edge runtime can mount a ServiceAccount token while omitting or clearing the standard Kubernetes Service environment variables and providing no route to the Kubernetes Service VIP. Unit tests and cloud-node behavior then make a Lease client look deployable even though the edge workload cannot reach its control-plane object.

**Suggested improvement:** Before enabling Lease-gated side effects, run a same-node, same-ServiceAccount probe that separately proves token/CA presence, endpoint routing, TLS verification and named-object RBAC. Model any nonstandard control-plane endpoint as an explicit approved contract value rather than relying on reserved environment variables.

**Principle:** Control-plane object support is end-to-end only when the exact edge workload identity can reach, authenticate to and authorize against the selected endpoint; API availability elsewhere in the cluster is not sufficient.

<!-- 2026-08-26 isolated Lease deployment checkpoint: Observation 21 captured. -->

### Observation 22: Make independently owned cutover planes conditional in the execution graph

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Live-testing Lease ownership handoff while the separate Service traffic-routing contract remained intentionally blocked.
**Skill:** New skill candidate: safe decision-to-execution planning
**Type:** open-source
**Phase/Area:** Execution planning, compensation, and multi-plane cutover
**Reference file:** `edge-orch/state-aggregator/app/runtime_execution_plan.py`

**Issue:** A plan can successfully hand off processing ownership and validate the new ACTIVE workload, then immediately treat an intentionally unsupported traffic-routing plane as a failure and compensate the already-valid Lease handoff. Expressing “switch traffic if supported and approved” as an unconditional sequential step couples two independently owned control planes and prevents an ownership-only migration from reaching a stable terminal state.

**Suggested improvement:** Resolve routing compatibility and approval while building the plan. Represent traffic cutover as an explicit conditional branch, and define whether its absence is a valid ownership-only terminal state or a fail-closed blocker before any mutation. Compensation should roll back only the plane whose approved invariant was violated, unless a cross-plane policy explicitly requires both to move together.

**Principle:** Independently owned cutover planes need explicit conditional graph semantics; an unavailable optional plane must not silently invalidate a completed transition in another plane.

<!-- 2026-08-26 live Lease handoff and candidate-failure checkpoint: Observation 22 captured. -->

### Observation 23: Preserve observation provenance when projecting live and persisted runtime state

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Extending an operations dashboard with live service state, persisted execution records, Lease snapshots and validation history.
**Skill:** New skill candidate: runtime operations interface
**Type:** open-source
**Phase/Area:** Runtime state modeling and operator-facing freshness

**Issue:** A dashboard often has a live source projection but only a persisted validation snapshot for a retained candidate. Rendering both with the same visual certainty makes an old Ready or ACTIVE result look current, even though the candidate may have failed or been scaled down after that observation.

**Suggested improvement:** Carry source, timestamp and age with every projected state; prefer the newest service-specific validation result for candidate readiness; label persisted evidence explicitly; and keep Pod Ready, execution ownership and traffic routing as independent fields rather than deriving one from another.

**Principle:** Operational projections must expose evidence provenance and age at the same level as status; combining observations from different clocks or authorities without that context creates false confidence.

<!-- 2026-08-26 runtime dashboard analysis/model/UI checkpoint: Observation 23 captured. -->

<!-- 2026-08-26 runtime dashboard test/browser/Semantica checkpoint: no additional observations; Observation 23 captures the provenance lesson. -->

### Observation 24: A remote branch must not execute the local algorithm eagerly

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Splitting a sensor service into Local and Remote inference executors with Local fallback.
**Skill:** New skill candidate: safe runtime offloading
**Type:** open-source
**Phase/Area:** Partial offloading and fallback boundaries
**Reference file:** `edge-orch/sensor-anomaly-demo/app/inference_executor.py`

**Issue:** Calling the local model before attempting the remote request preserves a convenient fallback value but still spends the edge CPU/GPU cost that offloading is meant to remove. It can also advance a stateful model twice and make Local and Remote results compete for authority.

**Suggested improvement:** Pass Local inference as a lazy callback, execute exactly one authoritative branch, and invoke Local only after a classified Remote failure. Carry one request ID through retries, reject stale/mismatched responses, and fence the final production commit with the workload ownership guard.

**Principle:** Partial offloading is real only when the displaced computation is not performed on the source during the successful remote path; fallback must be lazy and authority must remain singular.

<!-- 2026-08-26 runtime offloading executor/recommendation/dashboard checkpoint: Observation 24 captured. -->

### Observation 25: Separate protocol proof from accelerator qualification

**Status:** OPEN
**Date:** 2026-08-26
**Session context:** Live-testing remote inference while the only cluster GPU was occupied by an observed-only candidate whose performance qualification remained rejected.
**Skill:** New skill candidate: safe runtime offloading
**Type:** open-source
**Phase/Area:** Isolated cluster validation and promotion gates
**Reference file:** `edge-orch/state-aggregator/app/config/service_catalog.json`

**Issue:** A successful source-to-server request and fallback test proves transport, contract and continuity, but it does not prove that the GPU candidate is faster, uses the accelerator, or satisfies the approved placement profile. Reusing an occupied or rejected production candidate for convenience can blur those evidence classes and accidentally promote it.

**Suggested improvement:** Run protocol/failure tests in isolated workloads with explicit backend labels, preserve the Git qualification gate, report measured latency with the backend used, and require a separate accelerator-specific performance experiment before changing candidate qualification or enabling automatic recommendation.

**Principle:** Functional remote execution, accelerator utilization and performance superiority are independent claims and need independently attributable evidence.

<!-- 2026-08-26 runtime offloading image/manifest/live-cluster checkpoint: Observation 25 captured. -->

## 2026-08-31

### Observation 26: Reconcile design gates with newly produced qualification evidence

**Status:** OPEN
**Date:** 2026-08-31
**Session context:** Re-reviewing a platform design after its first technology qualification had been executed and documented.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Current-state reconciliation and decision gates

**Issue:** A design still described a qualification test as future work and kept the related adoption decision unresolved even though a newer qualification report recorded a conditional pass. The result did not make the component production-ready, but leaving both states unreconciled made the design stale and hid the remaining operational conditions.

**Suggested improvement:** During current-state review, search for artifacts named by every design gate and compare their dates, outcomes, scope exclusions, and residual conditions. Update the design to distinguish completed qualification, conditional development adoption, and production approval instead of collapsing them into pending or complete.

**Principle:** Decision-gated designs must be reconciled when new gate evidence appears; qualification evidence changes the decision state without automatically proving operational readiness.

### Observation 27: Distinguish platform-foundation priority from full downstream implementation

**Status:** OPEN
**Date:** 2026-08-31
**Session context:** Discussing whether field-specific service contracts or a shared model library should be implemented first.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Design review and implementation sequencing

**Issue:** A review treated “the model library comes first” as though it meant completing profiling, placement, and offloading before service work. That collapsed a thin shared foundation and its much larger downstream control plane into one priority, obscuring a valid architecture-first sequence.

**Suggested improvement:** When reviewing priorities, decompose platform capabilities into a minimum foundation and later consumers. Allow the registry contract, artifact identity, adapter boundary, and basic lookup to precede domain services, while deferring comprehensive profiling, placement, and mutation until concrete service contracts supply validation cases.

**Principle:** Architecture-first sequencing works when the first layer is a thin, testable contract; prioritizing a foundation does not require prematurely building every downstream capability.

### Observation 28: Do not persist an exploratory preference as a confirmed decision

**Status:** OPEN
**Date:** 2026-08-31
**Session context:** A user reconsidered an implementation-priority opinion immediately after it had been recorded as a durable project decision.
**Skill:** New skill candidate: durable project memory governance
**Type:** open-source
**Phase/Area:** Decision confirmation and memory writes

**Issue:** Tentative language expressing a current impression was converted directly into a confidence-1.0 durable decision. The user reversed the preference in the next exchange, requiring a superseding record and leaving avoidable noise in project memory.

**Suggested improvement:** Classify statements as exploration, preference, proposal, or confirmed decision before writing durable memory. Treat hedged phrases and active trade-off discussion as provisional; wait for explicit confirmation or an implementation action before recording them as authoritative, and record a clear supersession link when a prior entry must be corrected.

**Principle:** Durable memory should preserve settled project truth, not every intermediate opinion; confidence must reflect the speaker's commitment, not merely the clarity of the latest sentence.

### Observation 29: Separate the contractual recovery window from end-to-end failover

**Status:** OPEN
**Date:** 2026-08-31
**Session context:** Interpreting a sub-second recovery KPI for a containerized edge platform from its contractual definition and annual development plan.
**Skill:** New skill candidate: performance-KPI interpretation and qualification
**Type:** open-source
**Phase/Area:** Metric semantics, architecture boundary, and test protocol

**Issue:** A metric defined from error detection to resumed data transmission can be incorrectly presented as the time from physical failure to complete node detection, workload rescheduling, container startup, and state recovery. That changes both the measured interval and the architecture needed to satisfy it.

**Suggested improvement:** Trace each contractual KPI to explicit start and end events before assigning system components. Keep the official interval, detection latency, orchestration remediation time, and end-to-end outage as separate measurements, and design the critical path around the stated endpoint rather than an expanded interpretation.

**Principle:** Performance targets are meaningful only when their timing anchors and success event are preserved; never substitute a broader recovery workflow for the interval the contract actually defines.

<!-- 2026-08-31 재배치 추천 노드 판단 기준 문서화 plan checkpoint: no observations -->

## 2026-09-01

### Observation 30: Align docs image promotion with the Git revision Argo actually tracks

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Deploying generated documentation from a feature branch while the image-build workflow only triggered on the main branch.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Documentation image promotion and GitOps rollout

**Issue:** Pushing the branch tracked by Argo CD does not build a new image when CI only watches another branch. Reusing a mutable tag or updating Git before the immutable image exists can also leave the Argo revision, deployment manifest, and live image describing different document generations.

**Suggested improvement:** Inspect both the CI trigger and Argo target revision before deployment. Build and push a uniquely tagged image first, pin its verified digest in the manifest tracked by Argo, commit and push once, then verify the exact Git revision, deployment image digest, pod image ID, and live page content.

**Principle:** A documentation deployment is complete only when the tracked Git revision, immutable image digest, and live content converge under the same deployment owner.

### Observation 31: Prove fault injection restores the resource contract before timing recovery

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Preparing a live USB Serial recovery qualification for a Device Service that reopens a Kubernetes hostPath-mounted character device.
**Skill:** New skill candidate: live edge fault-injection qualification
**Type:** open-source
**Phase/Area:** Fault-injection preflight and recovery benchmarking
**Reference file:** `docs/가상화-노드-오류-복구시간.md`

**Issue:** A USB driver unbind/rebind can remove and recreate the host character device while the workload still holds a bind mount to the prior device node. A timing test can therefore measure a broken resource-identity contract rather than the application's retry behavior, or leave the device unavailable if the rebind path is not defined first.

**Suggested improvement:** Resolve the exact physical USB topology and stable path, record the current binding, select the narrowest reversible fault, include an automatic restore path in the injector, run one canary before repetition, and verify the stable path, workload readiness, recovery counter, and Core Data readback before continuing.

**Principle:** A recovery benchmark is valid only when fault injection restores the same resource contract that the recovering process is expected to reopen.

### Observation 32: Distinguish internal, externally presented, and overlay addresses

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Clarifying how edge nodes with LAN addresses are reached through a separate private external-access address range.
**Skill:** connect-kubeedge-edgecore
**Type:** open-source
**Phase/Area:** Establish the requested scope and select the network path

**Issue:** An externally presented RFC1918 address range was initially treated as a new VPN overlay allocation, even though hosts already retained separate LAN identities and the external range was an existing routed or translated access plane. That conflated three distinct roles and led to unnecessary address-allocation advice.

**Suggested improvement:** Before choosing a KubeEdge network path, explicitly classify each address as the node's LAN/InternalIP, an externally presented routed or NAT address, or an overlay tunnel address. Ask for the mapping mode only when it changes certificate, routing, or inbound-port requirements; do not assume that a newly mentioned private range needs to be allocated by WireGuard.

**Principle:** Address ranges describe reachability roles, not implementation mechanisms; classify the role and translation boundary before prescribing an overlay.

### Observation 33: Instrument recovery phase boundaries before tuning retries

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Diagnosing a 400 ms Serial recovery gate after a single live canary took more than two seconds.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Live recovery diagnosis and performance attribution
**Reference file:** `edgex/device-serial/internal/driver/reader.go`

**Issue:** A single end-to-end recovery duration and retry count could not distinguish device-node recreation, successful port opening, firmware silence, malformed startup bytes, and the first valid frame. Tuning heartbeat or retry delays against that aggregate value would target the wrong phase and an isolated passing retry could falsely look like a fix.

**Suggested improvement:** Before changing recovery behavior, instrument monotonic boundaries for detection, resource/port readiness, first byte, first valid payload, and downstream acknowledgement. Repeat the same narrow reversible fault enough times to reveal stable phase timing, and only tune the phase that dominates repeated failures.

**Principle:** Recovery optimization starts with phase attribution; an end-to-end timer says that a target was missed, while boundary timings identify which component can actually reduce it.

### Observation 34: Qualify serial recovery as a line-state and cadence pair

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Reducing Arduino Uno USB Serial recovery from repeated 1.8-second misses to a 400 ms gate.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Serial line control, firmware cadence, and live qualification
**Reference file:** `edgex/device-serial/internal/driver/hangup_linux.go`

**Issue:** Clearing retry delay or changing DTR bits after `open` did not reliably prevent an Uno reset, and suppressing the reset alone still left up to one sampling interval before the next valid frame. Treating either the host line state or firmware cadence as the whole recovery path produced intermittent passes and misleading root-cause claims.

**Suggested improvement:** Hold the exact port open before fault injection, compare `HUPCL` on/off with identical reconnects, then test the firmware sampling interval independently. Preserve the wire and pin contract, back up the active application, change one contributor at a time, and qualify the final pair through the production service's own phase metrics rather than only a standalone reader.

**Principle:** Sub-second serial recovery is a joint bound on reconnect line-state continuity and next-frame cadence; both must fit the budget, and the production path must verify their composition.

<!-- 2026-09-01 HUPCL/cadence implementation and 31-run live gate checkpoint: Observation 34 captured. -->

### Observation 35: Converge the image-updater tag before pinning its digest

**Status:** OPEN
**Date:** 2026-09-01
**Session context:** Publishing a uniquely tagged documentation image while Argo Image Updater continued to observe `docs-html:latest`.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Documentation image promotion and GitOps reconciliation

**Issue:** The Git Kustomize digest and a manual Argo image override both pointed to the new image, but the updater's observed mutable tag still resolved to the previous digest. On its next reconciliation, the updater rewrote the Application override and rolled the live deployment back even though Argo reported the resulting old state as Synced and Healthy.

**Suggested improvement:** Build and verify a unique tag first, promote that exact manifest to the mutable tag observed by the updater, confirm both tags resolve to the same digest, then commit the immutable digest and refresh Argo. Recheck the Application override, Pod image ID, and live content after the updater has reconciled.

**Principle:** GitOps convergence includes every writer of desired state; a pinned digest is not stable while an image updater observes a different manifest through its mutable tag.

### Observation 36: Pair plain-language KPI explanations with explicit evidence boundaries

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Explaining a qualified recovery-time result to non-specialists while adding an interactive documentation page.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Technical KPI communication and educational simulation
**Reference file:** `docs/400ms-복구-체험하기.md`

**Issue:** A simple analogy can make a latency target understandable, but it can also blur the difference between an educational calculation, a measured recovery interval, and a broader failover claim.

**Suggested improvement:** Put a short ELI5 explanation before the technical detail, then immediately link it to the measured interval, evidence, and exclusions. If an interactive model is useful, label it read-only and educational, separate its assumed values from observed results, and prevent it from being described as a live-control or test tool.

**Principle:** Plain-language performance documentation earns trust when every analogy remains tied to its measurement boundary and does not expand the operational claim.

### Observation 37: Rotate generated certificates when advertised addresses change

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Adding an externally presented private address to a live control-plane server certificate without replacing its CA.
**Skill:** connect-kubeedge-edgecore
**Type:** open-source
**Phase/Area:** Cloud-side certificate and advertised-address preparation

**Issue:** The server generates a certificate from advertised addresses only when its certificate Secret is absent; subsequent configuration changes reuse the existing Secret. Updating the advertised-address list and restarting therefore leaves the old SAN set in service unless certificate rotation is made explicit.

**Suggested improvement:** Add a version-specific preflight that inspects certificate-generation behavior. Before rotation, preserve the CA and a rollback copy of the current server Secret; update the advertised addresses, remove only the regenerable server-certificate Secret, restart the exact workload, and verify the served SANs plus existing client reconnections. Keep network reachability testing separate from certificate success.

**Principle:** Configuration that declares certificate identities is not effective until the served certificate is freshly verified; persistent generated secrets can outlive the configuration that originally produced them.

<!-- 2026-09-02 docs image publication checkpoint: no new skill observations beyond existing Observations 35 and 36. -->

<!-- 2026-09-02 docs live deployment completion: no additional skill observations; existing Observations 35 and 36 cover the workflow. -->

### Observation 38: Verify device identity on both sides of a container boundary

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Qualifying USB Serial recovery when a stable host symlink changed targets after device re-enumeration but a running container retained the prior character device.
**Skill:** New skill candidate: hot-plug device endpoint qualification
**Type:** open-source
**Phase/Area:** Container device mapping and recovery preflight

**Issue:** A stable character-device symlink on the host can be resolved to one major/minor pair when it is mounted into a container. After hot-plug or driver rebind, the host symlink may point to a new device while the running container still exposes the old device node, so application retries cannot recover the connection.

**Suggested improvement:** Before timing application recovery, compare the host and container-visible device identity before and after re-enumeration. Use an exactly scoped, host-managed endpoint directory whose device node can be replaced atomically, or a protocol-native endpoint, while preserving exact hardware identity and avoiding broad device-tree mounts.

**Principle:** A stable pathname is not sufficient proof of a stable hot-plug contract; recovery qualification must verify that the consumer observes the same renewed device identity as the host.
### Observation 39: Diagnose shared-root DiskPressure across storage authorities

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Investigating recurrent Kubernetes DiskPressure on a host that also runs interactive development tools and a separate Docker/BuildKit runtime.
**Skill:** New skill candidate: Kubernetes node disk-pressure forensics
**Type:** open-source
**Phase/Area:** Evidence collection and storage-authority boundaries

**Issue:** A large Linux memory page cache was initially suspected, but node events, kubelet config, kubelet summary statistics, and Prometheus history showed that a shared root filesystem was crossing the kubelet image-filesystem free-space threshold. CRI image garbage collection could not reclaim host files or caches owned by a separate runtime, so treating all disk use as container image cache obscured the failure boundary.

**Suggested improvement:** Define a diagnostic workflow that separates memory page cache from persistent disk use, reads kubelet node/image filesystem thresholds, correlates eviction events with filesystem time series, compares CRI image usage with host-visible directories and other runtimes, and reports unobservable transient writers as bounded hypotheses rather than proven causes.

**Principle:** Disk-pressure diagnosis must preserve storage authority boundaries; a kubelet can detect shared-filesystem pressure but can reclaim only the artifacts managed by its runtime.

<!-- 2026-09-02 container storage GC plan checkpoint: Observation 39 already captures the reusable workflow; no additional observations. -->

### Observation 40: Release outer query rows before nested pool acquisition

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Diagnosing EdgeX Core Data 503 responses and ingestion stalls under concurrent per-device Event queries.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Database connection-pool concurrency and query composition
**Reference file:** `edgex/core-data/patches/0001-core-data-device-query-pool-deadlock.patch`

**Issue:** Each request retained an outer Event query connection while its row callback acquired another connection for Reading rows. With N concurrent requests against a pool of size N, all N connections could remain held by outer iterators while every callback waited for an unavailable second connection, stalling both reads and ingestion.

**Suggested improvement:** Materialize the bounded outer result and close its rows before acquiring connections for nested queries, or fetch the related data through the same connection or a bounded join. Add a regression test whose concurrency equals the configured pool size and verify that all requests complete while ingestion remains fresh.

**Principle:** A database callback must not acquire a second pooled connection while it still owns an outer result connection unless the pool contract explicitly reserves that capacity.

### Observation 41: Explain performance changes as measured deltas

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Refining a plain-language recovery explanation after repeated requests for what was actually changed.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Technical KPI explanation and evidence presentation

**Issue:** Repeating an abstract recovery sequence did not answer how the implementation improved. The explanation became useful only after naming the prior behavior, the exact configuration or code change, and the before/after measurements for each contributing phase.

**Suggested improvement:** Add a documentation pattern for performance work: present a baseline-to-change-to-effect table, include exact configuration values and intermediate failed attempts, then show the final phase arithmetic and measurement boundary. Put the short causal summary after this evidence rather than substituting it for the evidence.

**Principle:** A performance-improvement explanation should make each claimed cause auditable as baseline behavior, exact intervention, and measured delta.

### Observation 42: Recover inactive candidates from fresh load evidence

**Status:** OPEN
**Date:** 2026-09-02
**Session context:** Validating hysteresis and tierwise recovery in a request-level inference routing prototype.
**Skill:** New skill candidate: durable runtime recommendation engines
**Type:** open-source
**Phase/Area:** Recovery latches and metric freshness
**Reference file:** `qualification/llama-offloading/placement.py`

**Issue:** Recovery of an inactive lower tier was gated by its historical latency and throughput EWMA. Because an inactive candidate produces no new service-performance samples, an old overload value could remain above the threshold forever and prevent fallback even while the candidate stayed healthy and idle.

**Suggested improvement:** Classify metrics by freshness and observability before using them in state transitions. For an inactive candidate, latch on continuously observed health and idle capacity for a recovery dwell, then use cooldown and one-tier-at-a-time fallback to limit oscillation; re-evaluate performance as new traffic arrives.

**Principle:** A recovery transition must not require fresh performance evidence from a component that receives no work; use observable idle health plus time bounds, and treat historical load-dependent metrics as stale.

### Observation 43: Separate control-agent liveness from inference residency

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Implementing comparable always-on, cold, and cached on-demand inference states behind a stable node API.
**Skill:** New skill candidate: serverless inference lifecycle qualification
**Type:** open-source
**Phase/Area:** Runtime state model and readiness contract
**Reference file:** `qualification/llama-offloading/worker.py`

**Issue:** Treating a node API process as the inference worker makes a COLD state impossible to observe or activate remotely, while treating any live process as READY risks routing requests before the model is resident. A small management process must remain reachable even when the actual inference runtime is stopped.

**Suggested improvement:** Define separate `agent_healthy`, `runtime_running`, `model_cached`, `model_loaded`, and `inference_ready` signals. Keep only a bounded control agent resident, start and stop the inference process through an explicit lifecycle contract, and require `inference_ready` before routing.

**Principle:** Lifecycle orchestration must distinguish management-plane availability from data-plane readiness and model residency; process presence alone is not a valid readiness signal.

### Observation 44: Verify the live mount source before trusting an edge emptyDir

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Deploying an on-demand model cache and lifecycle marker volume to a KubeEdge edge node and two ordinary Kubernetes nodes.
**Skill:** New skill candidate: KubeEdge workload storage diagnostics
**Type:** open-source
**Phase/Area:** Edge Pod ephemeral volumes and inference lifecycle
**Reference file:** `qualification/llama-offloading/k8s/workers.yaml`

**Issue:** The current edge Pod reported a normal `/models` mount in its spec, but `/proc/self/mountinfo` resolved it to the current Pod UID path suffixed with `//deleted`; file creation and Ollama pulls then failed with `ENOENT`. Identical `emptyDir` mounts on the two server nodes remained writable, so API health and Pod readiness alone did not expose the storage failure.

**Suggested improvement:** During edge workload qualification, compare the current Pod UID with `/proc/self/mountinfo` and perform a bounded write probe before model preparation. Keep management liveness independent of writable marker volumes, and prefer runtime-native model inventory/runner state when the cache only needs Pod-lifetime durability.

**Principle:** A declared or visibly mounted ephemeral volume is not evidence of a usable backing path on an edge node; validate the live mount source and the exact read/write operation before relying on it for lifecycle control.

### Observation 45: Separate saturation knee, SLO capacity, and failure ceiling

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Deriving inference offloading thresholds from repeated fixed-node load tests.
**Skill:** New skill candidate: inference saturation qualification
**Type:** open-source
**Phase/Area:** Capacity definitions and routing-policy calibration
**Reference file:** `qualification/llama-offloading/saturation-experiment-plan.md`

**Issue:** A single “maximum concurrency” hides three different operational boundaries: throughput stops scaling, latency violates the service objective, and the transport begins rejecting connections. Using the last successful request as capacity would route traffic into severe queueing, while using the first queued request would understate usable SLO headroom.

**Suggested improvement:** Report a throughput knee, an SLO-safe capacity, and a failure ceiling separately from the same repeated load curve. Use the earliest pressure signal only as a sustained review latch, then require an explicit predicted completion-time gain before offloading.

**Principle:** Capacity qualification should distinguish efficiency, service quality, and hard failure boundaries; routing policy should be calibrated to the earliest relevant service boundary, not the largest load that happened to complete.

### Observation 46: Treat Pod phase on unreachable edge nodes as stale evidence

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Read-only live status assessment of a KubeEdge and EdgeX platform after one edge node stopped reporting.
**Skill:** connect-kubeedge-edgecore
**Type:** open-source
**Phase/Area:** End-to-end verification and status reporting

**Issue:** Pods assigned to an unreachable edge node remained displayed as `Running` and even `1/1 Ready` in the API long after node heartbeats and monitoring samples stopped. Reading Pod phase alone would have incorrectly described the Device Service and node-level agents as healthy.

**Suggested improvement:** In the end-to-end verification section, require Pod readiness on an edge node to be qualified by current Node Ready/Lease evidence and fresh monitoring or endpoint evidence. Explicitly label Pod status from an unreachable node as stale control-plane state rather than current workload health.

**Principle:** A cached workload phase is not live evidence when its execution node is unreachable; operational status must join workload state with fresh node and endpoint observations.

### Observation 47: Current lifecycle facts must override cached transition details

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Verifying idempotent activation after deploying measured inference thresholds.
**Skill:** New skill candidate: serverless inference lifecycle qualification
**Type:** open-source
**Phase/Area:** Idempotent lifecycle responses and activation accounting
**Reference file:** `qualification/llama-offloading/tests/test_worker.py`

**Issue:** An already-active worker returned its cached last-activation record after first setting `activation_required=false`; dictionary merge order then let the historical `true`, prior source state, and old duration overwrite current facts. No new activation occurred, but downstream accounting could record one.

**Suggested improvement:** In idempotent lifecycle responses, merge cached diagnostic detail first and write current action/state fields last. Add a regression test that seeds a prior activation and proves a repeated activation reports no required action and the current state as the source state.

**Principle:** Historical transition detail may enrich an idempotent response, but it must never override whether an action occurred now or the component's current lifecycle state.

### Observation 48: Distinguish controller reconciliation time from fault onset

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Diagnosing whether a control-plane reboot caused an edge-node and workload outage that became visible immediately afterward.
**Skill:** connect-kubeedge-edgecore
**Type:** open-source
**Phase/Area:** Failure timeline reconstruction

**Issue:** After the control plane restarted, the node controller and taint manager emitted fresh registration, scheduling, and eviction events for an edge node whose last heartbeat and workload failure were already several days old. Using the newest event timestamp as the incident start would have blamed the reboot for a pre-existing outage.

**Suggested improvement:** In the troubleshooting section, reconstruct a joined timeline from host boot time, Node condition `lastHeartbeatTime` and `lastTransitionTime`, taint `timeAdded`, Pod creation/deletion timestamps, workload data freshness, and controller events. Treat post-restart controller events as reconciliation evidence unless a fresh node heartbeat or endpoint transition proves a new state change.

**Principle:** A controller event records when the controller processed state, not necessarily when the underlying fault began; causal diagnosis must anchor on source observations across the restart boundary.

### Observation 49: Separate active replicas from historical failed Pod objects

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Diagnosing a namespace that appeared severely unhealthy because many old evicted Pods remained beside one healthy replacement.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Kubernetes symptom classification

**Issue:** A flat Pod listing showed dozens of error-like statuses even though the current Deployment and ReplicaSet had one Ready replica and a live Service endpoint. Most entries belonged to an old ReplicaSet and had already reached terminal `Failed/Evicted` state, so counting rows overstated the present outage.

**Suggested improvement:** During Kubernetes root-cause investigation, group Pods by owner UID or ReplicaSet, desired replica count, terminal phase, creation time, and endpoint membership before judging service health. Report historical failure volume separately from current desired/available replicas and verify the active endpoint directly.

**Principle:** Object history and current service availability are different facts; incident severity must follow the active controller and endpoint graph, not the number of failed rows retained by the API.

### Observation 50: Scope dwell time over the complete overload expression

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Writing an ELI5 explanation of measured LLM offloading thresholds.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Policy documentation and verification
**Reference file:** `docs/Llama-오프로딩-부하-판단-기준.md`

**Issue:** Placing “2초 지속” next to only the queue signal can make readers think the dwell timer qualifies that one metric, while the runtime policy applies it to the complete `queue OR TTFT OR tokens/s` expression.

**Suggested improvement:** State that any one of the three signals must persist for two seconds, show the Boolean expression as a grouped block, and test wording that scopes the duration across the entire condition.

**Principle:** When time qualifies a Boolean policy, plain-language documentation must explicitly bind the duration to the whole expression rather than to the nearest clause.

### Observation 51: Verify terminated-Pod GC semantics before prescribing cleanup

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Explaining why a small namespace retained many failed Deployment Pods and evaluating safe automatic cleanup.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Kubernetes lifecycle diagnosis

**Issue:** It is easy to assume Kubernetes removes failed Pods after a fixed age or that `ttlSecondsAfterFinished` applies universally. In reality, the controller-manager's terminated-Pod GC is cluster-wide and count-triggered, while TTL-after-finished applies to Jobs, not Deployment-owned Pods. ReplicaSet revision retention also affects how long owner-linked failures remain visible.

**Suggested improvement:** Inspect the live controller-manager `--terminated-pod-gc-threshold`, cluster-wide terminal-Pod count, workload owner kind, and Deployment `revisionHistoryLimit` before recommending cleanup. Prefer a namespace-scoped, age-based policy when operators need predictable retention without changing cluster-wide forensic history.

**Principle:** Automatic cleanup must be designed against the actual owner and garbage-collector semantics; count limits, time limits, and revision history are separate mechanisms.

### Observation 52: Do not derive failed-Pod retention from mutable condition times

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Implementing and live-testing age-based cleanup for failed Deployment Pods after a control-plane reboot.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Kubernetes garbage-collection safety

**Issue:** A first cleanup implementation used the newest Pod condition `lastTransitionTime` as the failure clock. The restarted control plane rewrote conditions on two-day-old Evicted Pods, making all of them appear less than one hour old and preventing cleanup. Creation time alone is also unsafe because a long-running Pod may fail much later and then lose its diagnostic record immediately.

**Suggested improvement:** For controllers that need time-based retention of arbitrary terminal Pods, record a dedicated immutable-enough first-observed-failed annotation and age from that value. Use UID preconditions on deletion, preserve recent failures, and migrate already-diagnosed historical failures with an explicit timestamp before the first deletion run.

**Principle:** Retention clocks need a purpose-built timestamp; generic lifecycle condition timestamps are reconciliation state and are not reliable failure-time evidence.

### Observation 53: Never let a role label impersonate measured hardware

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Correcting an ELI5 capacity document after a CPU substitute role was read as a physical accelerator result.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Evidence labels in public performance documentation
**Reference file:** `docs/Llama-오프로딩-부하-판단-기준.md`

**Issue:** Repeating a target hardware name as a shorthand role in headings and capacity tables made CPU substitute measurements look like results from the physical device, even though a boundary note disclosed the substitution elsewhere.

**Suggested improvement:** Put “not measured on target hardware” in the title and first warning, map every logical role to its actual host and execution mode, qualify every result-table label as a substitute value, and add a negative regression assertion against ambiguous headings.

**Principle:** A benchmark label must identify the system that produced the evidence; intended deployment roles must never stand in for unmeasured hardware in headings, tables, or conclusions.

### Observation 54: Separate host identity from compute-backend identity

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Correcting a second benchmark-documentation error after an actual target edge board had been grouped with two substitute remote hosts.
**Skill:** docs-refresh-ko
**Type:** open-source
**Phase/Area:** Hardware evidence classification
**Reference file:** `docs/Llama-오프로딩-부하-판단-기준.md`

**Issue:** Treating “CPU-only” as equivalent to “not run on the target device” erased a valid fact: one worker ran physically on the intended board while only its GPU backend was disabled; two other workers ran on substitute hosts. A single global substitute label could not represent both conditions.

**Suggested improvement:** Record benchmark provenance as separate fields for physical host model, logical role, execution backend, accelerator visibility, and attribution. State results per row, never with one shared hardware disclaimer when the rows differ.

**Principle:** Where code ran and what processor executed it are independent dimensions; benchmark claims must preserve both before comparing devices or declaring evidence absent.

### Observation 55: Qualify available target hardware independently

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Correcting a multi-node accelerator benchmark after one available target device was unnecessarily forced into CPU mode because two remote target devices were unavailable.
**Skill:** experimental-design
**Type:** open-source
**Phase/Area:** Experimental preflight and missing-cell handling
**Reference file:** `qualification/llama-offloading/experiment-plan.md`

**Issue:** Downgrading every test role to a lowest-common-denominator backend made the comparison internally uniform but failed to answer the primary question for the target accelerator that was actually available. It also encouraged substitute-host results to fill cells that should have remained explicitly unmeasured.

**Suggested improvement:** Preflight physical host identity and execution backend per experimental cell. Measure each available target on the requested backend, mark unavailable target cells as unmeasured, and keep substitute runs in a separately labelled validation stratum rather than forcing all targets into the substitute mode.

**Principle:** Missing test environments must not downgrade available target environments; measure available targets as specified and leave unavailable comparison cells explicitly unmeasured.

### Observation 56: Separate idle GPU telemetry from schedulable GPU capacity

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Preparing GPU-backed LLM workers on two shared Kubernetes nodes whose GPUs were idle in telemetry but fully reserved by existing Pods.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Accelerator scheduling preflight

**Issue:** Low GPU utilization and low VRAM usage can look like free capacity even when the scheduler has already allocated every advertised `nvidia.com/gpu` device to other workloads. Starting another exclusive GPU Pod then requires disrupting an owner, enabling an approved sharing policy, or adding capacity.

**Suggested improvement:** Before scheduling accelerator experiments, inspect both live device telemetry and Kubernetes capacity/allocatable plus active Pod requests. Report utilization headroom and schedulable ownership as separate facts, and obtain explicit authorization before displacing a GPU owner or changing cluster-wide sharing.

**Principle:** An idle accelerator is not necessarily an available accelerator; eligibility requires both physical headroom and schedulable ownership.

### Observation 57: Audit whether the incumbent needs its accelerator before changing sharing

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Freeing a GPU for an LLM qualification run after an unrelated web service reserved the node's only accelerator without using it.
**Skill:** systematic-debugging
**Type:** open-source
**Phase/Area:** Accelerator scheduling remediation

**Issue:** After finding an idle-but-reserved GPU, the first remediation enabled node-wide time-slicing. The actual owner was a CPU-oriented web service with a stale `nvidia.com/gpu` limit, so sharing preserved the configuration error and weakened isolation for every workload on the node.

**Suggested improvement:** Trace the reservation to its owning workload and compare the declared accelerator resource with the process, runtime and service contract before selecting a remediation. Remove an unjustified request at the workload source; use time-slicing only when multiple legitimate GPU consumers are intentionally co-located and its lack of memory/fault isolation is acceptable.

**Principle:** Fix stale ownership before expanding shared capacity; cluster-wide sharing is not a substitute for correcting an unnecessary workload reservation.

### Observation 58: Verify the restored desired state after temporary capacity borrowing

**Status:** OPEN
**Date:** 2026-09-04
**Session context:** Temporarily scaling an Argo CD-owned GPU service to zero for an isolated accelerator benchmark, then restoring its original replica and health state.
**Skill:** New skill candidate: shared-accelerator-qualification
**Type:** open-source
**Phase/Area:** Temporary displacement and guaranteed restoration

**Issue:** Removing a temporary Argo override and immediately running `rollout status` against the still-scaled-zero Deployment returned success before Argo had reconciled the original replica count. Treating that command as restoration proof could leave the incumbent service stopped.

**Suggested improvement:** Capture the incumbent replica, health, endpoint, accelerator identity and scheduler allocation before borrowing capacity. Restore the GitOps override in a finally-style cleanup, then condition-wait for both the original desired replica count and Ready count before checking the API, accelerator identity, allocation and temporary worker scale-to-zero state.

**Principle:** Restoration is proven only against the captured pre-change state after the owner reconciles; rollout success on stale desired state is not recovery evidence.

### Observation 59: Keep admission recovery independent of edge connectivity

**Status:** OPEN
**Date:** 2026-09-07
**Session context:** Recovering a failed admission controller that had been scheduled onto a disconnected edge node and consequently blocked recreation of the cloud connection service.
**Skill:** connect-kubeedge-edgecore
**Type:** open-source
**Phase/Area:** Cloud-side recovery prerequisites

**Issue:** An unrestricted admission-controller placement created a recovery dependency cycle: its missing endpoint blocked the service needed to reconnect its own edge host. Restoring the controller on a verified server reopened admission without disabling webhook enforcement. An independent image-filesystem pressure condition then delayed dependent workloads even though the server remained Ready.

**Suggested improvement:** Inspect webhook service endpoints, admission-controller placement, namespace exemptions, node pressure conditions and exact FailedCreate/FailedScheduling events before restarting edge agents. Verify the webhook with server-side dry-run after recovery, then verify dependent services and node reconnection. Respect the measured pressure transition interval rather than clearing a taint by hand.

**Principle:** Recovery infrastructure must not depend on the connectivity it restores; verify admission and scheduling readiness separately from node heartbeat readiness.

<!-- 2026-09-07 pod cleanup checkpoint: no new skill observations; terminal UID-guarded cleanup and live readiness verification completed. -->

<!-- 2026-09-07 disk diagnosis/cleanup checkpoint: no new skill observations. User reversed cordon; cache reclamation and readiness verified. -->

<!-- 2026-09-07 live button/GPU restoration checkpoint: existing Observations 20, 23 and 58 applied; persisted ownership, honest interrupted records and desired/Ready/health restoration verified. No new skill observation. -->

### Observation 60: A local pilot does not complete a comparative decision-boundary experiment

**Status:** OPEN
**Date:** 2026-09-07
**Session context:** User requested empirical routing, activation and reclamation criteria across heterogeneous GPU devices and corrected a handoff focused on a local pilot.
**Skill:** experimental-design
**Type:** open-source
**Phase/Area:** Completion gates and measurement boundaries

**Issue:** Tooling, unit tests and a local load ramp established instrument functionality but did not answer the comparative objective. Extending to an origin-side paired experiment required matching runtime settings, obtaining compatible artifacts from a verified local cache, distinguishing process limits from device capacity, and preserving authorization boundaries around an incumbent workload.

**Suggested improvement:** Before handing off, map each requested decision to a necessary comparison and evidence ID. Require requester-side local/remote observations for routing claims, include explicit warmup in startup estimates, and distinguish active-wave throughput from calendar-span throughput when arms are interleaved. Mark unresolved authorization and unmeasured arms individually, without treating the local pilot as the comparative result.

**Principle:** Instrument validation is a prerequisite, not a substitute, for evidence that resolves the user's comparative decision.

**Reference file:** qualification/llama-boundaries/README.md

### Observation 61: Verify deployment through the image updater's source of truth

**Status:** OPEN
**Date:** 2026-09-08
**Session context:** A verified documentation rollout disappeared from the homepage after an automated image reconciliation.
**Skill:** docs-refresh-ko; verification-before-completion
**Type:** open-source
**Phase/Area:** Deployment ownership and persistence checks

**Issue:** Patching the application's image digest passed immediate Pod and HTTP checks, but a separate image updater tracked an unchanged mutable registry tag and reverted the application. Kubernetes managed fields identified the updater as the later writer.

**Suggested improvement:** Inspect updater annotations and write-back ownership before deployment. Promote a verified uniquely tagged image through the tracked release tag when that is the existing contract, then observe a subsequent updater cycle and verify the homepage, search index, application digest and running imageID together.

**Principle:** A rollout is not durably verified until every active reconciler agrees with the intended release source.

### Observation 62: Own long-running benchmark processes on the measured device

**Status:** OPEN
**Date:** 2026-09-10
**Session context:** Three-device, six-model GPU performance experiment
**Skill:** academic-research-suite
**Type:** internal
**Phase/Area:** Remote experiment lifecycle and evidence recovery

**Issue:** A management exec disconnect terminated a request client while its native GPU server survived. Terminal-only journaling left one in-flight request without an outcome; a later device-detached run completed all requests even when management queries failed.

**Suggested improvement:** For remote experiment execution, preflight a device-owned timeout, exact PID and exit receipts, durable local request-dispatch and terminal journals, and checksum-verified result export after the client settles. Retry read queries independently; never replay an uncertain inference request. Keep unsent, successful, failed and missing-terminal requests distinct.

**Principle:** A management connection is an observation channel, not a workload lifetime or completion guarantee; durable execution and request accounting must live with the workload.

**Reference file:** qualification/llama-boundaries/results/multimodel-three-devices-20260910-b/nano/qwen2.5-3b-instruct-q8_0-b0/interruption-reconciliation.json

### Observation 63: Transfer restoration ownership before benchmark continuations overlap

**Status:** OPEN
**Date:** 2026-09-10
**Session context:** Three-device, six-model GPU performance experiment
**Skill:** academic-research-suite
**Type:** internal
**Phase/Area:** Remote experiment lifecycle and evidence recovery

**Issue:** The parent experiment finished one device and attempted to restore the shared service while a slower continuation re-suspended it. The parent restoration wait timed out, and its old watchdog would later race the still-active continuation unless explicitly handed over.

**Suggested improvement:** For multi-device continuations, define one restoration owner before launching the continuation, persist its PID identity and resource UID, and hand off the watchdog atomically. Require the final owner to wait for every owned workload to stop, then compare the live service specification, readiness, container identity and experiment-process absence with the original snapshot.

**Principle:** Restoration is a coordinated shared-resource operation; independent successful device runs must not create competing cleanup owners.

**Reference file:** qualification/llama-boundaries/results/multimodel-three-devices-20260910-b/restoration-handoff.json

<!-- task-observer checkpoint 2026-09-10 multimodel final deliverable: no additional observations; entries 62 and 63 verified present. -->
