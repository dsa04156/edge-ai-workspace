---
name: connect-kubeedge-edgecore
description: Inspect this repository and its live KubeEdge cluster, then plan, execute, or troubleshoot onboarding a new Linux Jetson, Raspberry Pi, or ASUS Tinker Edge R node through EdgeCore and keadm. Use for requests to add, join, reconnect, replace, or validate a KubeEdge edge node in the jinuk Edge AI PoC, including CloudCore reachability, version matching, containerd and old-kernel runtime compatibility, partial netfilter diagnosis, registry transfer, EdgeCore configuration, node labels, EdgeMesh/DNS, Prometheus visibility, and dashboard verification. Keep KubeEdge limited to node and workload management; do not treat KubeEdge Device resources as the EdgeX physical-device authority.
---

# Connect KubeEdge EdgeCore

Connect one Linux edge host to the existing PoC through `edgecore`. Derive mutable values from the live cluster instead of copying stale examples.

## Load the local context

1. Read the repository `AGENTS.md` and obey its EdgeX/KubeEdge authority boundary.
2. Read [references/environment.md](references/environment.md) for the current topology, source precedence, and repository assets.
3. Read [references/runbook.md](references/runbook.md) before proposing or executing a join.
4. Read [references/naming-and-edgemesh.md](references/naming-and-edgemesh.md) when assigning a hostname or handling EdgeMesh.
5. Read [references/upstream-script-coverage.md](references/upstream-script-coverage.md) when the user references `dsa04156/kubeedge-setup-scripts`, asks whether every setup asset is covered, or requests cloud bootstrap/reset/offline installation.
6. For failures, old vendor kernels, registry pull stalls, or partial netfilter support, also read [references/troubleshooting.md](references/troubleshooting.md).

Do not use `docs/archive/`, legacy orchestration code, MapperFramework, or `mappers/mqttvirtual/` as the current onboarding design.

## Establish the requested scope

Identify these inputs from the request, live cluster, or target host:

- unique node hostname following `etri-devNNNN-jetorn`, `etri-devNNNN-raspi5`, or `etri-devNNNN-tedger`
- host address and SSH access path
- CPU architecture: `arm64` or `amd64`
- hardware class: Jetson, Raspberry Pi 5, or ASUS Tinker Edge R
- direct factory LAN or WireGuard path
- intended workload or physical-device role
- whether the task is inspect/plan only, execute join, reconnect, or destructive rebuild

Make read-only inspections without asking. Ask only for a missing target host/access path or a material role choice that cannot be discovered. Do not infer authorization to reset an existing node.

## Enforce safety gates

- Pin the Kubernetes context explicitly for every cluster mutation. Show the context and target node before joining or labeling.
- Confirm the hostname is unique in the cluster before running `keadm join`.
- Determine the active KubeEdge version from live Helm state and existing edge nodes. Require the CloudCore and EdgeCore release versions to match exactly unless a separately verified compatibility exception is documented. Never accept the repository's historical `v1.22.0` default without live confirmation.
- Require an active `containerd`, synchronized time, supported architecture, working CloudCore route, a compatible `keadm` binary, and the kernel/iptables features required by Flannel and EdgeMesh. Test built-in features functionally instead of treating missing module metadata or a failed `modprobe` as decisive. Require actual IPv4 `filter`/`nat`, bridge forwarding, VXLAN, and `physdev`, `multiport`, `comment`, and `statistic` match probes. Do not join a node that fails these required probes.
- Report missing IPv4 `mangle`/`raw` or IPv6 iptables separately. They are not a blanket blocker when the current IPv4 Flannel/EdgeMesh/DNS/workload path passes end to end, but they prohibit claiming full netfilter coverage and remain a kernel rebuild risk.
- Treat the join token as a secret. Never place it in source files, patches, plans, reports, chat excerpts, shell tracing, or persistent logs. Generate it immediately before use, pass it through a hidden interactive variable, and unset it after the join.
- Do not run `kubeedge_k8s_full_reset.sh`, flush iptables/nftables, overwrite WireGuard configuration, remove CNI state, or delete an existing Kubernetes Node unless the user explicitly requests a rebuild and the exact target is re-confirmed.
- Do not mix Calico and Flannel. Inspect the active cluster CNI before installing or changing networking.
- Do not expose CloudCore directly to a public network merely to make a join work. Use the repository WireGuard path for an external edge and verify certificate/address compatibility before joining.
- Do not deploy workloads, mutate EdgeX metadata, publish commands, or register a physical device as an implicit side effect of joining the node.
- Do not run historical cloud bootstrap, dynamic-controller RBAC, metrics-server, nginx demo, or full-reset assets merely because they exist in the upstream setup repository. Select them only for an explicitly verified need.

## Follow the onboarding workflow

### 1. Inspect the cloud side

Collect the current context, CloudCore Helm/app version, CloudCore pod node and host address, service ports, ready endpoint, existing edge versions, CNI, and relevant DaemonSets. Stop if CloudCore is not ready or versions disagree.

Prefer the host-network CloudCore endpoint advertised by the live deployment. Do not join against its ClusterIP.

### 2. Inspect the target edge host

Confirm hostname, architecture, OS, active containerd socket, time synchronization, swap and kernel networking prerequisites, disk space, existing EdgeCore state, and reachability to the selected CloudCore endpoint. On vendor kernels, inspect `/proc/filesystems`, `/proc/net/ip_tables_names`, relevant sysctls, a disposable network namespace, and real iptables commands before deciding that a built-in feature is absent.

If `/etc/kubeedge/config/edgecore.yaml` or an `edgecore` service already exists, classify the task as reconnect/rejoin. Diagnose before changing it.

### 3. Select the network path

- For a host on the current factory LAN, use the live CloudCore host address and required ports.
- For an external host, configure and verify WireGuard first. Allocate a unique peer address, exchange public keys without exposing private keys, verify a handshake, then test the CloudCore ports through the tunnel.

Do not continue when only ICMP succeeds; test the actual TCP ports.

For the requested LAN path, require a private IPv4 CloudCore host and set the system hostname before `keadm join`. Never join with a temporary hostname and try to rename the Kubernetes Node afterward.

### 4. Prepare and join EdgeCore

Use the repository's `kubeedge-tools/onboard-edge-lan.sh` for a new LAN host. It validates the ETRI hostname, prepares kernel networking, calls `setup-edge.sh` with an explicit live-confirmed version, collects the token through a hidden prompt, joins, and patches the generated EdgeCore YAML. Verify the installed `keadm` version rather than assuming the setup script replaced an existing binary.

Treat bundled `crictl v1.20.0` and CNI plugin `v0.9.0` tarballs as retained offline bootstrap assets, not the desired current versions. Prefer compatible packages already installed on the target, and report when an old bundled asset was actually used.

On an old kernel, run a disposable container before joining. Diagnose a reproducible runtime crash independently of EdgeCore. Use only checksummed upstream binaries, and pin the smallest compatible runtime change; for the verified Debian 10/kernel 4.4 Tinker path, read troubleshooting before selecting runc.

If an external registry repeatedly resets large blob downloads, fetch the exact ARM64 image on the trusted operator host, verify its digest and transfer checksum, import it into the edge containerd namespace, and remove the transfer archive after verification. Do not expose or proxy credentials. Configure the PoC HTTP registry only for its exact LAN host under containerd `certs.d`; never disable TLS verification globally.

Generate the token on the cloud side only when the edge host is ready. `patch-edge.sh` must receive the approved node name, hardware class, and LAN CloudCore host; it must reject an incompatible generated YAML shape instead of partially editing it.

Inspect the resulting YAML before and after restart. Require its websocket, HTTP, and stream servers to point to the selected CloudCore address, `edgeStream.enable: true` when CloudStream is active, EdgeMesh DNS `clusterDNS: [169.254.96.16]`, and `hostnameOverride` equal to the approved unique node name.

### 5. Apply only current node identity

Expect `keadm` to add the `node-role.kubernetes.io/edge` and `node-role.kubernetes.io/agent` roles. Add `environment=edge` after the node registers. Add a hardware-class or service-specific label only from verified inventory and an actual scheduling need.

Do not add `edge.device/mapper=mqttvirtual`; that label belongs to a legacy test path. Do not repoint exact-hostname workload manifests merely because a new node exists.

Run `kubeedge-tools/finalize-edge-lan.sh` from the cloud operator host with an explicit context. Require the existing edge Flannel, EdgeMesh agent, and node-exporter DaemonSets to become Ready on the new node. Do not reinstall EdgeMesh for each node.

### 6. Verify end to end

Require all of the following:

- EdgeCore systemd active with no continuing certificate, websocket, runtime, or hostname errors
- Kubernetes Node present and `Ready`, with the expected roles, architecture, runtime, and InternalIP
- CloudCore ready and logging the new node connection without a repeated failure loop
- repository EdgeCore join check exits without failures
- an edge-targeted smoke Pod can be created and reaches cluster DNS/Service routing
- `kubectl logs` for the smoke Pod succeeds through CloudStream/EdgeStream
- required node-level monitoring DaemonSets cover the node and Prometheus has a fresh node sample
- `state-aggregator` `/state/nodes` shows the node with the expected identity and evidence

Report warnings separately from failures. Do not call the onboarding complete if Node Ready is true but DNS, runtime, or dashboard/Prometheus evidence is missing.

## Preserve the platform boundary

Joining EdgeCore proves only KubeEdge node/workload connectivity. It does not prove a sensor, PLC, camera, or Device Service is connected.

Handle physical-device integration as a separate follow-up:

1. confirm the protocol endpoint and stable physical identity
2. bind an approved EdgeX Device Service workload to the exact node when needed
3. register the Device Profile and Device through EdgeX Core Metadata
4. require Device Service communication and a fresh Core Data Event
5. verify dashboard device freshness separately from Kubernetes Node Ready

Keep write commands, actuator mutation, runtime offloading, and dashboard-side Kubernetes/EdgeX mutation disabled unless separately approved and implemented.

## Produce a concise handoff

Include:

- node identity, architecture, and selected network path
- discovered CloudCore endpoint and matched KubeEdge version, excluding tokens
- actions performed and files changed
- evidence for EdgeCore, Node Ready, DNS/Service routing, monitoring, and dashboard visibility
- workload/device integration deliberately not performed
- unresolved warnings or risks and the exact next safe action
- the exact distinction between verified current IPv4 operation and any unimplemented kernel networking tables
