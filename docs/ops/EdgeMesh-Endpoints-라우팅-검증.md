# EdgeMesh selectorless Service·Endpoints 라우팅 검증

## 결론

2026-08-26 live KubeEdge/EdgeMesh 클러스터의 격리 namespace에서 selectorless Service와
controller-owned core `Endpoints`를 사용해 다음 전환을 실제 HTTP 응답과 EdgeMesh
libp2p 로그로 확인했다.

```text
source(etri-dev0001-jetorn)
→ candidate(etri-dev0002-raspi5)
→ source(etri-dev0001-jetorn)
```

이 결과는 현재 배포된 EdgeMesh가 core `Endpoints` 변경을 읽어 edge node 사이 Service
traffic을 전환할 수 있다는 근거다. `EndpointSlice` 전용 경로를 입증한 결과는 아니며,
현재 Runtime Execution Controller는 아직 `runtime-endpointslice` 모드이므로 운영 계약은
계속 fail-closed 상태다.

## 검증 환경

| 항목 | 값 |
|---|---|
| kubectl context | `kubernetes-admin@kubernetes` |
| KubeEdge | `v1.23.0` |
| EdgeMesh chart | `edgemesh-0.1.0` |
| EdgeMesh image | `kubeedge/edgemesh-agent@sha256:460c6061b6088d507bb547d362a8d803b75c7eeddd23758a4b218a5da9138364` |
| EdgeMesh DaemonSet | 6 desired / 6 Ready |
| 검증 namespace | `edge-ai-routing-proof-20260826` |
| source | `routing-source`, `etri-dev0001-jetorn`, `10.244.2.73` |
| candidate | `routing-candidate`, `etri-dev0002-raspi5`, `10.244.1.245` |
| probe | `routing-probe`, `etri-dev0003-raspi5`, `10.244.4.158` |
| Service | `routing-proof`, ClusterIP `10.100.184.138`, selector 없음 |

세 Pod는 같은 ARM64 immutable image digest를 사용했고 모두 Ready와 실제 imageID 일치를
확인했다. probe는 같은 Service FQDN을 1초 간격으로 호출했다.

## Routing object

Kubernetes endpoint-slice mirroring을 사용하지 않도록
`endpointslice.kubernetes.io/skip-mirror=true`를 지정했다. 검증 Service와 연결된
EndpointSlice가 없음을 별도로 확인했다.

Endpoints에는 다음 소유권과 상태 label을 사용했다.

```yaml
edge-ai.io/managed-by: routing-proof-controller
edge-ai.io/service-id: routing-proof
edge-ai.io/routing-role: active
edge-ai.io/active-target: source | candidate
edge-ai.io/execution-plan-id: <proof transition id>
```

초기 source snapshot의 resourceVersion은 `24688584`, candidate 전환 후는 `24688641`,
source rollback 후는 `24688706`이었다.

## 관측 증거

Endpoints가 없을 때 probe는 연결 실패를 반환했다. source Endpoints 생성 직후부터 다음과
같이 source 응답이 연속 관측됐다.

```text
2026-08-26T02:30:38.253196+00:00 HTTP source
...
2026-08-26T02:30:54.430792+00:00 HTTP source
```

Endpoints address를 candidate Pod로 변경한 뒤 같은 FQDN 요청이 candidate 응답으로 전환됐다.

```text
2026-08-26T02:30:55.435486+00:00 HTTP candidate
...
2026-08-26T02:31:15.528293+00:00 HTTP candidate
```

저장한 source address로 Endpoints를 복구한 뒤 다시 source 응답이 연속 관측됐다.

```text
2026-08-26T02:31:16.537268+00:00 HTTP source
...
2026-08-26T02:31:42.829967+00:00 HTTP source
```

probe node의 EdgeMesh agent 로그도 실제 대상 node와 Pod IP를 구분해 기록했다.

```text
Dial libp2p network between routing-source -
  {tcp etri-dev0001-jetorn 10.244.2.73:8080}

Dial libp2p network between routing-candidate -
  {tcp etri-dev0002-raspi5 10.244.1.245:8080}
```

source와 candidate HTTP server 로그에는 각각 EdgeMesh 경유 요청과 HTTP 200이 기록됐다.

## 안전성과 정리

- `sensor-anomaly-demo` Service, Deployment, PVC와 EndpointSlice는 변경하지 않았다.
- 검증 전후 production Service selector는
  `app.kubernetes.io/name=sensor-anomaly-demo`로 동일했다.
- production EndpointSlice는 계속 `endpointslice-controller.k8s.io` 소유이며 address는
  `10.244.2.72`, node는 `etri-dev0001-jetorn`이다.
- 검증 종료 후 `edge-ai-routing-proof-20260826` namespace 전체를 삭제하고 부재를 확인했다.

## 입증 범위와 다음 조건

이번 검증이 입증한 것은 현재 EdgeMesh에서 selectorless Service와 controller-owned core
Endpoints를 사용한 단일 endpoint의 source→candidate→source atomic 전환이다.

아직 입증하거나 구현하지 않은 항목은 다음과 같다.

- Runtime Execution Controller의 `runtime-endpoints` 모드
- sensor-anomaly-demo production Service의 Git selectorless 전환
- execution SQLite snapshot을 이용한 실제 Controller rollback
- 30초 post-switch validation과 자동 rollback의 production E2E
- 동시 execution lock과 stale resourceVersion conflict의 live 검증
- source 종료와 candidate promotion

다음 구현은 Service patch 없이 core Endpoints만 `get/list/watch/update`하고, exact 소유권 label,
serviceId/namespace/name/port, resourceVersion과 저장 snapshot이 일치할 때만 변경하는
`runtime-endpoints` routing mode다. 기존 EndpointSlice 전용 구현을 운영에서 활성화하면 안 된다.
