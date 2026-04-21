# State Aggregator Monitoring

`state_aggregator` now exposes Prometheus-format metrics at `/metrics`.

Kubernetes manifests:
- `deployment.yaml`: Deployment + Service
- `service-monitor.yaml`: kube-prometheus `ServiceMonitor`

Apply order:

```bash
kubectl apply -f state-aggregator/k8s/deployment.yaml
kubectl apply -f state-aggregator/k8s/service-monitor.yaml
```

Expected scrape path:

```text
http://state-aggregator:8000/metrics
```

If your kube-prometheus stack uses a different `ServiceMonitor` selector label than
`release: prometheus`, update `service-monitor.yaml` to match your cluster's
Prometheus configuration.

Grafana dashboard import file:

```text
state-aggregator/grafana/state-aggregator-dashboard.json
```

Import that JSON into Grafana and bind the `Prometheus` datasource when prompted.
