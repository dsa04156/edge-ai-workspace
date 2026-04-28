---
name: traefik-service-link
description: Add, modify, verify, and GitOps-sync Traefik routing for a new Kubernetes service. Use when Codex needs to expose a service through Traefik IngressRoute or Ingress resources, add a path or host route, choose/apply a middleware such as StripPrefix, update Argo CD-managed manifests, or debug why a service route is not reachable.
---

# Traefik Service Link

## Workflow

1. Identify the target Kubernetes Service before editing manifests.
   - Run `kubectl get svc -A | rg '<service-name>|<namespace>'`.
   - Confirm namespace, service port, selector, backing pods, and whether the app expects a path prefix or root path.
   - If the service has no ready endpoints, stop and fix the workload first.

2. Locate the project routing pattern.
   - Prefer repo manifests over live-only edits.
   - For this project, read `edge-orch-argocd/edge-orch-ingressroute.yaml` for edge platform API paths.
   - Read `edge-orch-argocd/traefik-services-ingressroute.yaml` for shared monitoring and Argo CD paths.
   - Read `traefik/*.yaml` for host-based examples using `*.192.168.0.56.sslip.io`.
   - See `references/project-patterns.md` for concrete patterns.

3. Add or modify the smallest matching route.
   - Use `apiVersion: traefik.io/v1alpha1`, `kind: IngressRoute` when the repo already uses IngressRoute.
   - Use `entryPoints: [web]` unless the cluster has an existing HTTPS entrypoint in the same manifest set.
   - For path routing, use `PathPrefix(\`/<prefix>\`)`.
   - For host routing, use `Host(\`<name>.192.168.0.56.sslip.io\`)` unless the user gives another domain.
   - Route to the Kubernetes Service name and service port, not the container port unless they are the same.

4. Handle prefixes deliberately.
   - If the backend serves correctly only at `/`, attach the existing StripPrefix middleware used by the manifest set.
   - If the backend is configured with a base path such as `/dashboard` or `/argocd`, do not strip the prefix unless the existing route proves that is required.
   - Do not create duplicate middlewares unless no existing middleware matches the prefix behavior.

5. Validate before syncing Git.
   - Run `kubectl apply --dry-run=server -f <manifest>` for changed manifests when the CRD is available.
   - Run `kubectl get ingressroute -A` and `kubectl describe ingressroute <name> -n <namespace>` after apply/sync.
   - Check endpoints with `kubectl get endpoints -n <namespace> <service-name>` or EndpointSlices.
   - Test locally with `curl -I` or `curl -sS` against the Traefik URL.

6. Keep GitOps authoritative.
   - Commit only the manifest and support-file changes required for the route.
   - Push to the branch tracked by Argo CD.
   - Force Argo CD refresh only after Git contains the desired state.
   - If live `kubectl apply` is used for immediate verification, confirm Argo CD does not revert it.

## Project Commands

Use these checks as a baseline:

```bash
kubectl get svc -A | rg '<service-name>|<namespace>'
kubectl get pods -n <namespace> -o wide
kubectl get endpoints -n <namespace> <service-name>
kubectl get ingressroute -A
kubectl apply --dry-run=server -f <changed-ingressroute.yaml>
```

After Git sync:

```bash
git status --short --branch
git add <changed-files>
git commit -m "feat: expose <service-name> through traefik"
git push origin main
kubectl annotate application -n argocd <app-name> argocd.argoproj.io/refresh=hard --overwrite
kubectl get application -n argocd <app-name> -o jsonpath='{.status.sync.status}{"\n"}{.status.health.status}{"\n"}'
```

## Output Standard

Report:

- The exposed URL or path.
- The manifest file changed.
- The Kubernetes Service and port used.
- Whether a prefix middleware is attached.
- Validation commands and results.
- Git commit hash and push status when requested.
