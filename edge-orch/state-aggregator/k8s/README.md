# State Aggregator Monitoring

`state_aggregator` now exposes Prometheus-format metrics at `/metrics`.

Kubernetes manifests:
- `deployment.yaml`: Deployment + Service
- `service-monitor.yaml`: kube-prometheus `ServiceMonitor`

Workflow UI는 별도 registry ConfigMap을 사용하지 않는다. 등록 Device는
state-aggregator가 Kubernetes Device/DeviceStatus와 InfluxDB telemetry를 조회해
`/state/devices` 및 `/state/devices/{device_id}/telemetry`로 제공한다.

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
