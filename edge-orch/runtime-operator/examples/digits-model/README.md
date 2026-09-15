# 공통 추론 계약: 실제 손글씨 숫자 분류

`digits-classifier`는 학습된 최근접 중심 모델로 8×8 손글씨 이미지를 0~9로 분류한다.
Llama와 다른 입력·모델을 같은 RuntimeService/gateway/운영 화면으로 연결하는 실행 검증이다.
옥동 품질 판별·설비 이상감지 모델이나 성능 실증을 대체하지 않는다.

## 현재 운영과 사용

어그리게이터 **OFFLOAD DEMO → digits-classifier**를 선택한다.
서비스 실행을 누르면 준비 후 실제 요청 위치가 맵에 표시된다. `시험 요청 1건`은 등록 이미지
한 건을 추론한다. 현재 실행 노드의 `부하 주기`를 누르면 해당 서비스에 이미지 추론 요청을
계속 보내며, 처음 시작한 노드의 `부하 제거`로 멈춘다. 다른 노드의 시작 버튼은 현재 경로가
될 때 활성화된다. CPU 스트레스 프로세스나 GPU 소진 시험이 아니다.
서비스 중지는 시험 요청 생성을 멈추고 진행 요청을 정리한 다음 worker Pod를 종료한다.
검증 종료 시 서비스는 중지 상태이고 새 반복 부하 실행 이력은 없다.

현재 정책은 `preferred`다. 실행체 장애·배치 정책 변경은 후보 재평가 대상이지만,
**부하 기반 자동 증강·저부하 자동 복귀는 미활성**이다. ARM64/AMD64 실행 성공은
처리량 자격이 아니다. `qualifiedRps`·`qualifiedP95Milliseconds`는 비어 있고
`modelRuntime`에 `automatic`을 지정하면 계약 검증이 거부한다.

## 모델과 공통 계약

- 데이터: [scikit-learn digits](https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html), UCI Optical Recognition of Handwritten Digits 유래.
- 학습 입력: scikit-learn `1.7.2`의 [digits.csv.gz](https://raw.githubusercontent.com/scikit-learn/scikit-learn/1.7.2/sklearn/datasets/data/digits.csv.gz). URL과 SHA256을 고정한다.
- 알고리즘: 정답별 평균 이미지 10개를 학습하고 제곱 거리 최소 클래스를 반환한다.
- 재현: 저장소 루트에서 `rtk proxy python3 edge-orch/runtime-operator/model-worker/train.py`.
- 학습 1,433 / 평가 364장, 정답 325장(89.29%). [training.json](../../model-worker/training.json)에 분할과 모델 SHA를 기록했다. 일반 현장 정확도가 아니다.
- `input.json`은 정답 7인 알려진 성공 평가 표본이다. smoke 확인용이며 별도 정확도 시험이 아니다.
- 추론 서버는 Python 표준 라이브러리와 저장된 모델만 사용한다. 실행 시 학습·외부 다운로드가 없다.

`modelRuntime`는 [Open Inference Protocol V2](https://kserve.github.io/website/docs/concepts/architecture/data-plane/v2-protocol)의
고정 shape JSON 텐서 부분집합이다. KServe controller 전체나 binary/streaming 프로토콜 구현은 아니다.
입력 `pixels: FP32[1,64]`는 0~16의 64개 픽셀이고 출력은 `class: INT64[1]`,
`squared_distances: FP64[1,10]`다. 모델 SHA256을 `modelVersion`으로 사용한다.

등록 → `POST /services/digits-classifier/invoke` → 공통 adapter → worker
`/v2/models/digits-centroid/infer` → 모델/요청 identity와 출력 schema 검증 순서다.
`X-Request-ID`가 필요하며 같은 ID·같은 입력은 원장 응답을 재조회한다. dispatch 뒤에는 다른
worker로 자동 재시도하지 않는다. `/ready`는 기존 ioContract/ready/inFlight와 모델 메타데이터를
함께 검증한다. 새 실행체 준비 뒤 신규 요청을 넘기고 기존 요청을 마무리한다.

## 등록과 이미지 재생성

[service.yaml](service.yaml)은 처음부터 `suspended: true`다. `verifiedNodes`에는 모델 실행을
직접 확인한 노드만 추가한다. hostname 단계 분기는 없고 아키텍처·역할·자원 조건과 함께
후보를 판단한다. 신규 노드 추가만으로 기존 worker revision이 바뀌지 않는다.

운영자는 기존 runtime-operator/CRD 배포 뒤 등록한다.

```sh
rtk proxy kubectl apply -f edge-orch/runtime-operator/examples/digits-model/service.yaml
```

worker Dockerfile은 다음 기존 Python 이미지 중 해당 아키텍처의 것을 `BASE_IMAGE`로 받는다.
모델과 서버 파일을 덮어쓰므로 기존 합성 HTTP 서버는 실행하지 않는다.

| 아키텍처 | Python 기반 이미지 |
|---|---|
| arm64 | `192.168.0.56:5000/runtime-contract-demo@sha256:0c70aaa5f6f1d3f01bb71e6e6656ceac5bdc197cd23ac0f5c1239883d67d8005` |
| amd64 | `192.168.0.56:5000/runtime-contract-demo@sha256:425836c63f64d6659892bc42d96700dc61edd55b3d8b8bfe37fcabcd52e4d558` |

Dockerfile 재빌드 시 이미지 digest는 달라질 수 있다. 게시된 각 digest와 실제 서버·모델 파일
SHA는 [검증 결과](../../results/2026-09-15-generic-model/README.md)에 고정했다.
다른 AI를 추가하려면 고정 입출력 계약을 제공하는 worker, 아키텍처별 실행 이미지,
노드별 실행 검증을 등록한다. 성능 자격과 자동 정책 일반화는 다음 단계다.
