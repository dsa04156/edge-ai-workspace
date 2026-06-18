# 자원증강형 가상디바이스 대시보드 계획

## 목적

이 문서는 가상디바이스를 센서 생성기가 아니라 물리 디바이스의 부족한
CPU/GPU/NPU/storage를 보강하는 논리 자원 객체로 표현하기 위한 dashboard
구성 기준을 정리한다.

현재 구현은 운영 가시화와 dry-run binding preview 범위다. Kubernetes workload
생성, runtime migration, 자동 offloading, Device CR mutation은 수행하지 않는다.

## 모델

자원증강형 가상디바이스는 두 층으로 본다.

| 층 | 의미 | dashboard 표시 |
|---|---|---|
| Resource Profile | 구성 가능한 보강 자원 정의 | AI HAT Inference, x86 GPU Inference, Jetson GPU-lite, Storage Cache |
| Resource Instance | 현재 관측되는 실행체 | Pod/container/service endpoint, node readiness, binding state |

Resource Profile은 registry seed 또는 향후 `VirtualDevice Registry`에서 온다.
Resource Instance는 Kubernetes/Prometheus/service resource profile에서 관측한다.

## 상태

| 상태 | 의미 |
|---|---|
| `configured_not_running` | registry에는 있으나 실행 인스턴스가 관측되지 않음 |
| `idle` | 실행 중이나 workflow/stage에 아직 bind되지 않음 |
| `allocated` | 특정 workflow/stage에 사용 중 |
| `partially_available` | 여러 인스턴스 중 일부는 allocated, 일부는 free |
| `degraded` | 실행 중이나 load, endpoint, storage/cache 등 일부 문제가 있음 |
| `unavailable` | 실행 인스턴스가 있으나 node/pod/endpoint가 unavailable |
| `unknown` | registry 또는 관측 데이터가 불완전함 |

대시보드는 0/1/N 인스턴스를 모두 표시한다. 실행 중인 인스턴스가 없다는 이유로
Resource Profile을 숨기지 않는다.

## 화면 구조

### Resource Command Center

- 자원 프로파일 수
- 실행 인스턴스 수
- 사용 가능 자원 수
- 바인딩된 인스턴스 수
- 실행 안 됨 수
- 주의/장애 수
- Resource Pool table
- Resource Twin Inspector

### Workflow Resource Lane

workflow canvas는 다음 관계를 dry-run으로 보여준다.

```text
Physical device/source
  -> preprocess/feature stage
  -> AI inference/resource stage
  -> dashboard event
```

AI inference/resource stage는 Resource Profile 또는 Resource Instance에 bind된다.
이 bind는 현재 브라우저/UI 상태와 execution plan preview로만 표현한다.

### 엣지 디바이스 자원증강 워크플로

현재 `자원증강` 탭의 대표 서비스 워크플로는 Jetson/Raspberry Pi 같은
엣지 디바이스의 부족 자원을 외부 실행 자원으로 보강하는 dry-run이다.

```text
target edge device
  -> resource gap detection
  -> augmentation resource binding
  -> remote inference execution
  -> result cache binding
  -> augmented device status
```

역할 분리는 다음과 같다.

| 단계 | 실행 위치/의미 |
|---|---|
| target edge device | `etri-dev0001-jetorn`, `etri-dev0002-raspi5` 같은 물리 엣지 디바이스다. |
| resource gap detection | 대상 디바이스가 직접 감당하기 어려운 GPU/AI/storage 요구를 식별한다. |
| augmentation resource binding | x86 GPU, AI HAT, Jetson GPU-lite, storage cache 같은 보강 자원에 매핑한다. |
| remote inference execution | 무거운 AI 추론 또는 전처리 작업은 서버/다른 엣지 자원에서 실행된다. |
| result cache binding | 결과 window, 모델 cache, 산출물 저장을 외부 cache/storage 자원에 연결한다. |
| augmented device status | 운영자는 대상 엣지 디바이스의 실행 능력이 보강된 상태로 본다. |

이 워크플로는 센서 source를 가상으로 생성한다는 뜻이 아니다. 물리 엣지
디바이스는 대상 device로 남고, 부족한 연산/저장 능력을 외부 실행 자원으로
보강한다. 현재 dashboard는 `device_augmentation=jetson-gpu-storage-augmentation`
에 대해 선택 가능한 inference/storage 가상디바이스와 실행 계획을 read-only로
표시한다.

## Kubernetes 관리 표면

자원증강을 Kubernetes-native 운영 객체로 관리하기 위한 CRD와 읽기 전용 status
controller는 다음 경로에 둔다.

```text
edge-orch/device-augmentation/crds/
edge-orch/device-augmentation/samples/
edge-orch/device-augmentation/k8s/
edge-orch/device-augmentation/controller/
```

CRD는 두 종류다.

| kind | scope | 의미 |
|---|---|---|
| `AugmentationResource` | Cluster | 엣지 디바이스를 보강할 수 있는 GPU/NPU/AI HAT/storage 자원 정의 |
| `DeviceAugmentation` | Namespaced | 특정 엣지 디바이스와 보강 자원 사이의 binding 정의 |

적용 예시는 다음과 같다.

```bash
kubectl apply -k edge-orch/device-augmentation/crds
kubectl apply -k edge-orch/device-augmentation/samples
kubectl apply -k edge-orch/device-augmentation/k8s
kubectl get augmentationresources
kubectl get deviceaugmentations -n default
kubectl get augmentationresource vd-x86-gpu-inference -o yaml
kubectl get deviceaugmentation jetson-gpu-storage-augmentation -n default -o yaml
```

현재 controller는 `/state/virtual-resources` 관측값과 `AugmentationResource`
선언값을 읽어 CRD `status`만 reconcile한다. 이 status는 `kubectl get
augmentationresources`, `kubectl get deviceaugmentations -n default`에서 확인할
수 있다. 상세 status에는 runtime observation, endpoint readiness,
capability satisfaction, selected resource role이 `conditions`와
`selectedResources`로 표시된다. workload 생성/이동, 자동 offloading,
runtime migration은 구현하지 않는다.

## 대표 서비스 시나리오

현재 포함된 실행 시나리오는 Jetson 비전 검사 자원증강이다.

```text
etri-dev0001-jetorn
  -> jetson-gpu-storage-augmentation
  -> vd-x86-gpu-inference
  -> vd-storage-cache
```

시나리오 파일은 다음 위치에 둔다.

```text
edge-orch/device-augmentation/scenarios/jetson-vision-inspection/
```

이 overlay는 `AugmentationResource`/`DeviceAugmentation` 샘플과 시나리오
ConfigMap을 함께 적용한다. 정상 기준은 다음이다.

- `DeviceAugmentation` `jetson-gpu-storage-augmentation`의 `phase=Ready`
- `selectedResources`에 `inference=vd-x86-gpu-inference`,
  `storage=vd-storage-cache`가 표시됨
- 두 `AugmentationResource`가 모두 `phase=Available`,
  `endpointReady=true`
- dashboard `자원증강` 탭의 plan preview가 같은 CRD status를 read-only로 표시

자동 확인은 다음 명령으로 수행한다.

```bash
python3 tools/check_resource_augmentation_scenario.py --base-url http://127.0.0.1:8000
```

## 현재 구현 경계

현재 dashboard frontend는 `state-aggregator`의 read-only API인
`/state/virtual-resources`, `/state/augmentation-resources`,
`/state/device-augmentations`를 조회한다. Backend는 고정 registry seed,
`/state/resource-profiles` 계열에서 쓰는 service resource observation,
Kubernetes `AugmentationResource`/`DeviceAugmentation` CRD status를 병합해 보여준다.

- observation이 정상일 때: 관측된 service resource profile을 기준으로 observed instance를 계산한다.
- 여러 node에 걸친 profile은 registry에 지정된 augmentation node의 pod/container만 해당 Resource Instance로 계산한다.
- Prometheus/resource observation이 실패할 때: registry seed는 계속 표시하고 observed instance는 0으로 둔다.
- `/state/dashboard`도 service resource observation 실패 시 dashboard shell과 기본 device/node KPI를 유지하고,
  resource profile KPI만 0과 observation error로 degrade한다.
- `AugmentationResource` CRD status는 dashboard의 resource observation 보조 신호로 사용한다.
- `DeviceAugmentation` CRD status는 workflow resource lane의 binding/condition/selected resource 근거로 표시한다.
- 상태 표현은 read-only/dry-run이다.

현재 추가한 API 표면은 다음과 같다.

```text
GET /state/virtual-resources
GET /state/virtual-resources/{id}
GET /state/virtual-resources/{id}/twin
GET /state/augmentation-resources
GET /state/device-augmentations
```

이 API는 Resource Profile, observed instances, resource twin snapshot,
workflow/stage binding state, CRD `conditions`, `selectedResources`를 반환한다.
현재 binding state는 read-only 관측값이며, 실제 Kubernetes apply/delete/restart
또는 workload migration으로 이어지지 않는다.

dashboard의 `자원증강` 탭은 다음 순서로 상태를 합성한다.

```text
/state/virtual-resources
  -> Resource Pool, Resource Twin Inspector, observed runtime count

/state/device-augmentations
  -> Workflow Resource Lane의 CRD phase, condition validation, selected resource role/node

/state/augmentation-resources
  -> Kubernetes CRD resource phase, endpoint readiness, conditions
```

운영자가 확인해야 하는 핵심 문장은 다음이다.

```text
이 Jetson/Raspberry Pi는 Kubernetes DeviceAugmentation CRD로 어떤 보강 자원에
연결되어 있고, 그 자원의 runtime/endpoint/condition이 Ready인지 확인할 수 있다.
```

## 표현 원칙

사용할 표현:

- 자원증강형 가상디바이스
- Resource Profile / Resource Instance
- 실행 인스턴스
- Resource Twin
- read-only / dry-run binding
- execution plan preview

피할 표현:

- 가상 센서 생성
- 자동 offloading 완료
- runtime migration 실행
- LLM 또는 dashboard가 Kubernetes 조치를 직접 수행
