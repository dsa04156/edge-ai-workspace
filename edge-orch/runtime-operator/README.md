# 공통 서비스 실행 제어기

전체 노드의 계약·호환성·예약 자원·서비스 부하를 기준으로 Kubernetes RuntimeService를
조정한다. 장비 이름과 고정 이동 순서는 구현에 없다.

설계, 지원 계약, 운영 책임, 실제 시험과 한계는
[공통 서비스 Kubernetes 오케스트레이션](../../docs/공통-서비스-Kubernetes-오케스트레이션.md)을 따른다.

## 설치 및 등록

운영자가 Kubernetes 관리 context와 등록할 immutable image를 확인한 뒤 실행한다.
기본 manifest는 platform-runtime namespace만 변경하며 EdgeX 운영 배포에 포함되지 않는다.

```bash
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -k edge-orch/runtime-operator/k8s
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -f edge-orch/runtime-operator/demo/services.yaml
rtk proxy kubectl --context kubernetes-admin@kubernetes -n platform-runtime get runtimeservices
rtk proxy kubectl --context kubernetes-admin@kubernetes -n platform-runtime port-forward service/runtime-gateway 18880:8080
```

ClusterIP만 제공한다. 승인된 합성 fixture 시험은 port-forward 후 다음과 같이 명시적으로
실행한다. 이 스크립트는 실제 요청을 발생시키므로 일반 단위시험에 포함하지 않는다.

```bash
rtk proxy python3 edge-orch/runtime-operator/scripts/smoke-http.py --base-url http://127.0.0.1:18880 --output /tmp/runtime-smoke.json
```

실행 환경은 state-aggregator의 고정 dependencies를 재사용한 이미지다. 배포 이미지는
고유 tag로 빌드 후 manifest에 digest를 고정한다. `scripts/build-images.sh`는 checksum
검증한 crane 실행파일과 고유 tag를 입력받는다. demo 이미지는 ARM64/AMD64 각각 생성한다.

## 검증

```bash
rtk proxy python3 -m pytest -q edge-orch/runtime-operator/tests
rtk proxy python3 edge-orch/runtime-operator/scripts/generate-crd.py
rtk proxy kubectl --context kubernetes-admin@kubernetes apply --dry-run=server -f edge-orch/runtime-operator/k8s/crd.yaml
```

서비스 중단은 RuntimeService의 `spec.suspended`를 true로 변경한다. 삭제는 finalizer가
drain을 마치도록 기다린다. 결과가 불명인 요청은 임의로 재실행하거나 원장에서 지우지 않는다.
