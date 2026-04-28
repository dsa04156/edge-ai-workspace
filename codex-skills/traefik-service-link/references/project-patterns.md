# Project Traefik Patterns

Use this reference when editing Traefik routes in `/home/etri/jinuk`.

## Main Files

- `edge-orch-argocd/edge-orch-ingressroute.yaml`: path-based routes for edge orchestration services in `default`.
- `edge-orch-argocd/traefik-services-ingressroute.yaml`: path-based routes for monitoring services and Argo CD.
- `traefik/grafana-ingressroute.yaml`, `traefik/argocd-ingressroute.yaml`, `traefik/prometheus-ingressroute.yaml`: host-based `sslip.io` route examples.
- `edge-orch-argocd/*ingress.yaml`: older or alternative Kubernetes Ingress resources; prefer IngressRoute when the adjacent route already uses it.

## Existing Path Route Shape

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: edge-orch-ingressroute
  namespace: default
spec:
  entryPoints:
    - web
  routes:
    - match: PathPrefix(`/aggregator`)
      kind: Rule
      services:
        - name: state-aggregator
          port: 8000
      middlewares:
        - name: strip-edge-orch-prefix
```

Use this shape when adding another edge platform API under a path prefix.

## Existing Host Route Shape

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: grafana
  namespace: kube-system
spec:
  entryPoints:
    - web
  routes:
    - match: Host(`grafana.192.168.0.56.sslip.io`)
      kind: Rule
      services:
        - name: prometheus-grafana
          port: 80
```

Use this shape when a service needs a clean root URL and can be addressed with a host name.

## Middleware Notes

- `strip-edge-orch-prefix` is used by existing `/aggregator`, `/executor`, and `/placement` routes.
- `strip-service-prefix` is used by `/prometheus` and `/grafana`.
- `strip-argocd-prefix` is used by `/argocd`.
- Confirm middleware namespace scope before referencing it from another namespace.
- If the middleware does not exist in the target namespace, either create it in Git or use a host route instead of path stripping.

## Validation Checklist

1. `kubectl get svc -n <namespace> <service-name> -o wide`
2. `kubectl get endpoints -n <namespace> <service-name>`
3. `kubectl apply --dry-run=server -f <ingressroute-file>`
4. `kubectl get ingressroute -n <namespace> <route-name> -o yaml`
5. `curl -I http://<host-or-ip>/<prefix>` or `curl -I http://<host>`
6. Check Argo CD application status if the file is GitOps-managed.
