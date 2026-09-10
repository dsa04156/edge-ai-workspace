# 모빌인트 NPU 코어 분리 데모

한 NPU를 받은 서버 안에서 두 모델이 서로 다른 코어를 사용한다. 여러 서비스는 이
서버의 API를 호출할 수 있다. Kubernetes가 코어를 Pod별로 쪼개 주는 구조는 아니다.

## 현재 구성

- 노드: `etri-ser0004-cgnms0` (일반 Kubernetes worker, VPN `10.77.0.10`).
- ARIES2 16 GiB, 드라이버 1.14.0, qb Runtime/CLI 1.4.0. 펌웨어는 flash하지 않았으며 새 조회 API는 기존 펌웨어를 1.2.4로 표시한다.
- `mobilint-demo/mobilint-core-demo`: 단일 Pod, `mobilint.com/npu: 1`, Recreate 배포.
- Candy → Cluster0/Core0, Mosaic → Cluster0/Core1. 모델마다 별도 Python 프로세스.
- 기존 장비의 Single 모드 MXQ 예제를 사용한다. 입력은 seed로 생성하는 합성 배열이다.
- 애플리케이션은 CDI로 장치를 전달받으며 privileged/hostPath를 사용하지 않는다.
- 동일 모델의 중복 요청은 409, 다른 모델의 요청은 병렬 처리한다.
- 시간 초과/worker 오류 후에는 큐를 재사용하지 않고 readiness 실패 및 liveness 재시작으로 복구한다.

## 직접 시험

상태: <http://10.254.70.228:31881/models> (JSON).
동일 서비스의 VPN 주소는 `http://10.77.0.10:31881`이다.
NodePort 31881은 `externalTrafficPolicy: Local`로 해당 Pod가 있는 노드에서 제공한다.
이 주소는 인증 없는 제한된 합성 입력 시험 API다. 외부 인터넷 공개용 API가 아니다.

```bash
rtk proxy curl -sS http://10.254.70.228:31881/demo/parallel \
  -H 'Content-Type: application/json' -d '{"seed":7,"iterations":20}'
rtk proxy curl -sS http://10.254.70.228:31881/infer/candy \
  -H 'Content-Type: application/json' -d '{"seed":7}'
```

`seed`는 0..4294967295, `iterations`는 1..50이다. 파일 업로드, 모델 경로, 센서 연결,
URL 입력은 받지 않는다. 응답은 실행 코어, 출력 shape/checksum, 추론 시간이다.
`overlap_ms`는 **호스트의 SDK 추론 호출 구간이 겹친 시간**으로 커널 타임라인이 아니다.
장비 모니터의 코어별 프로세스/사용률과 함께 판단한다. 영상 품질이나 성능 보장 시험은 아니다.

## 공식 플러그인과 드라이버 업데이트

현재 플러그인은 모빌인트 공식 v1.1.1 원본이다. `plugin/resources.yaml`은 공식 이미지
`ghcr.io/mobilint/mobilint-device-plugin`의 검증 digest에 고정되어 있으며 호환 패치와
`MOBILINT_ARIES2_DRIVER_1_8` 환경변수를 사용하지 않는다.

2026-09-09 드라이버 1.8 → 1.14, 런타임·CLI 0.30.0 → 1.4.0으로 전환했다.
공식 호환표상 드라이버 1.11 이상은 Runtime 1.0 이상이 필요하므로 애플리케이션도
`maccel`에서 `qbruntime`으로 전환하고 이미지를 다시 빌드했다. 기존 MXQ 모델은 그대로 사용한다.
기존 `mobilint-npu-runtime` 0.30 패키지는 복구용으로 남아 있지만 현재 Pod는 사용하지 않는다.
옛 SDK를 사용하는 별도 factory 예제는 새 드라이버와 호환된다고 보장하지 않는다.

NPU Pod와 플러그인을 중지하고 모듈 참조가 0인 상태에서 설치했다. 첫 설치 시도는
Pod 종료 유예 중이라 드라이버의 사용 중 보호 검사로 중단됐고, 종료 완료 후 정상 설치했다.
재부팅 없이 새 모듈을 로드했다. DKMS는 현재 커널 `6.8.0-79-generic`과 설치된 다른 커널
`6.8.0-138-generic` 모두 설치 완료다. 후자 커널로 실제 부팅하는 시험은 하지 않았다.

`/metrics`의 `mobilint_npu_health=1`, 메모리·코어별 사용률, `/process`의 두 모델 프로세스를
조회·검증했다. 전력 계측값은 0으로 보고되어 전력/에너지 분석에 사용하지 않는다.
대시보드/Prometheus 수집 설정까지 연결한 것은 아니다.

백업은 장비의 `/var/backups/mobilint-20260909/`에 원래 driver/SDK/CLI deb 및 DKMS 소스로
보관한다. 복구 시에는 NPU 소비 Pod와 플러그인을 먼저 중지하고 참조 0을 확인한 뒤
드라이버·CLI·컨테이너 이미지를 일치하는 이전 조합으로 되돌려야 한다.

`plugin/aries2-driver-1.8.patch`와 최초 시험 결과는 이력/복구 참고용으로 남긴다.
이 패치는 현재 드라이버에서 사용하지 않으며 현재 플러그인을 빌드할 때 적용하지 않는다.

## 재배포와 중지

저장소 루트에서 실행한다. 운영 책임은 시험 운영자에게 있으며 EdgeX Argo root에 포함하지 않는다.
두 manifest는 내부 registry의 검증 이미지 digest에 고정되어 있다.

```bash
rtk proxy kubectl --context=kubernetes-admin@kubernetes label node etri-ser0004-cgnms0 mobilint.com/npu.present=true --overwrite
rtk proxy kubectl --context=kubernetes-admin@kubernetes apply -k edge-orch/mobilint-demo/plugin
rtk proxy kubectl --context=kubernetes-admin@kubernetes -n kube-system rollout status ds/mobilint-device-plugin
rtk proxy kubectl --context=kubernetes-admin@kubernetes apply -k edge-orch/mobilint-demo/k8s
rtk proxy kubectl --context=kubernetes-admin@kubernetes -n mobilint-demo rollout status deploy/mobilint-core-demo
rtk proxy python3 edge-orch/mobilint-demo/verify.py http://10.77.0.10:31881 /tmp/mobilint-api-check.json
```

중지만 할 때에는 Deployment를 scale 0으로 내리면 NPU가 반환된다. 완전 제거 시에는
`k8s`를 delete한 뒤 `plugin`을 delete한다. 다른 NPU 소비자가 추가된 경우 먼저 확인한다.

```bash
rtk proxy kubectl --context=kubernetes-admin@kubernetes -n mobilint-demo scale deploy/mobilint-core-demo --replicas=0
```

## 이미지 재생성

애플리케이션 build context에는 `app.py`, `Dockerfile`과 아래 파일 네 개가 필요하다.
바이너리는 Git에 넣지 않으며, 복사 후 `assets.sha256`과 비교한다. 비밀번호를 파일이나
명령 인자에 넣지 않고 SSH 인증을 사용한다. 모델/SDK는 내부 시험 이미지에만 보관한다.

| 장비 원본 경로 | build context 파일 |
| --- | --- |
| PyPI `mobilint-qb-runtime==1.4.0`의 cp311/manylinux_2_31_x86_64 wheel | `mobilint_qb_runtime-1.4.0-cp311-cp311-manylinux_2_31_x86_64.whl` |
| `/usr/lib/x86_64-linux-gnu/libqbruntime.so.1.4.0` | 같은 파일명 |
| `/opt/.factory_test/demo/mxq/style_candy.mxq` | `style_candy.mxq` |
| `/opt/.factory_test/demo/mxq/style_mosaic.mxq` | `style_mosaic.mxq` |

amd64 환경에서 context를 현재 디렉터리로 두고 `rtk proxy sha256sum -c assets.sha256`,
`rtk proxy docker build -t 192.168.0.56:5000/mobilint-core-demo:새태그 .`를 실행한다.
내부 registry에 push한 digest로 `k8s/resources.yaml`을 갱신하고 실장비 시험을 다시 수행한다.

플러그인은 공식 이미지를 직접 사용한다. SDK/드라이버를 올릴 때에는
[드라이버 호환표](https://docs.mobilint.com/aries/en/compatibility.html)와
[MXQ 호환표](https://docs.mobilint.com/runtime/v1.4/en/compatibility.html)를 확인한다.

## 검증 근거와 한계

- [업데이트 후 API 시험](results/2026-09-09-upgrade-api.json): 단일 추론, 같은 seed 출력 재현,
  별도 클라이언트 동시 호출, 병렬 50회, 입력 400/모델 404/충돌 409.
- [공식 플러그인 telemetry](results/2026-09-09-upgrade-telemetry.json): 병렬 추론 중 메모리·코어 사용률·프로세스.
- [업데이트 후 배포 상태](results/2026-09-09-upgrade-deployment.json): 버전·이미지·Ready·기존 센서 상태.
- Python 계약 테스트 4개 통과. 최초 1.8 호환 패치의 테스트 결과와 API 증거는
  `results/2026-09-09-api.json`, `results/2026-09-09-deployment.json`에 이력으로 보존한다.

Pod별 코어/메모리/장애 격리, QoS 보장, 센서 서비스 바인딩, 옥동 AI 서비스 구현,
자동 이동·offloading, 대시보드 전용 화면은 이 데모의 완료 기능이 아니다.

참고: [공식 플러그인](https://github.com/mobilint/mobilint-device-plugin),
[코어 모드](https://docs.mobilint.com/aries/en/core-mode.html),
[SDK 0.30](https://docs.mobilint.com/runtime/v0.30/en/advanced_usage.html).
