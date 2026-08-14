# server1 observed-only inference candidate

이 구성은 현재 GPU 여유가 확인된 `etri-ser0002-cgnmsb`의 observed-only inference 후보 endpoint와
`AugmentationResource` 관측 계약을 준비한다. 상위 `k8s/kustomization.yaml`에 포함되어
Argo CD가 Pod·Service·NetworkPolicy·후보 CRD를 관리한다. 요청 전환은 활성화하지 않는다.

server1 컨테이너는 `SERVICE_ROLE=inference-server`로 실행한다. 이 역할에서만
`POST /api/v1/inference`가 열리며 `okdong.pump-motor.telemetry/v1`의 X/Y/Z/온도와
각 origin을 모두 요구한다. 요청 `requestId` 재전송은 기존 결과를 반환하고 같은 ID의
다른 payload는 `409`로 차단한다. frame과 온도 origin 차이가 허용 범위를 넘으면 `422`다.

현재 CUDA online baseline은 저장된 학습 artifact가 아니라 입력으로 warm-up되는 모델이다.
HAMi scheduler에 GPU 1개, GPU core 20%, GPU memory 1,024MiB를 요청하고, CuPy가 실제 CUDA
장치에서 probe kernel을 실행한 뒤에만 runtime 준비로 인정한다.
따라서 shadow Pod는 `INFERENCE_WARMUP_SOURCE_ENABLED=true`로 동일한 read-only Local Data
API를 관측해 모델을 준비한다. `/api/v1/augmentation-readyz`는 이 모델이 warm-up을 끝낸
뒤에만 200을 반환한다. 이것은 server1이 추론 요청을 받을 수 있다는 근거이지 edge 요청이
server1으로 전환됐다는 근거가 아니다.

Docker daemon 없이 `scripts/build-server1-oci.sh`로 linux/amd64 image를 생성한다. 스크립트는
`crane` archive checksum, Python 3.11 amd64 base digest와 Server1 전용 CuPy dependency를
고정한다. 실제 배포 image digest는 manifest와 live Pod `imageID`를 함께 확인한다.
다음 항목을 live로 검증해야 overlay를 운영 경로에 포함할 수 있다.

- Pod `Ready`와 `/api/v1/augmentation-readyz` 200
- `sensor-anomaly-inference-server1` Service EndpointSlice 생성
- 모델 `ready`, `accelerator=cuda`, 입력 `fresh`, server1 CPU·Memory·GPU 여유
- `AugmentationResource.status.phase=Available`, `endpointReady=true`, `freeInstances>0`

2026-08-13 `etri-ser0001-cg0msb` CPU 기반 선택 overlay에서 다음 observed-only 기준선 증거를 확인했다. 아래 값은
GPU 전환 완료 증거가 아니며 GPU image 배포 후 새로 측정해야 한다.

- `etri-ser0001-cg0msb` Pod Ready, restart 0, 위 AMD64 imageID 일치
- Service EndpointSlice `10.244.0.154`, `ready=true`
- 입력 `fresh`, 모델 `ready`, frame/context 802건, 입력·정렬 오류 0
- p95 20.739ms, backlog 0, throughput 3.706/s, CPU 30m, Memory 47Mi
- inference 응답 200, 동일 `requestId` 재전송 결과 동일, 다른 payload 재사용 409

현재 live `state-aggregator`는 Argo CD가 기존 revision image로 되돌리므로 새 virtual-resource
registry와 evaluator의 live CRD 상태 연결은 아직 검증하지 못했다. 소스와 checkout image
digest는 준비됐지만 Git revision 승격 전까지 dashboard live 반영으로 설명하지 않는다.

이 overlay는 shadow 관측만 수행한다. 요청 라우팅, offloading, retry, timeout, rollback,
자동 workload 변경은 포함하지 않는다.
