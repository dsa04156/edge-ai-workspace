# 실제 센서 입력 자동 운영

기존 `llama-inference`를 EdgeX raw 온도 요약 입력으로 연결한다. 별도 서비스 복제가
아니므로 이전 `llama-three-tier/service.json`을 동시에 적용하지 않는다.

```bash
rtk proxy kubectl --context kubernetes-admin@kubernetes apply -k edge-orch/runtime-operator/examples/edgex-sensor
```

먼저 이 입력 profile을 지원하는 `runtime-operator/k8s`를 적용해야 한다. Operator는
배치·준비·전환·원장을 소유한다. `edgex-ai-input`은 별도 단일 replica·Recreate 소비자로,
기존 EdgeXClient와 공통 요청 adapter만 실행한다. 대시보드 Deployment를 변경하지 않는다.

`spec.commonAI.input`의 Device/Profile/resource와 5초 polling을 사용한다. 서비스 중지는
기존 RuntimeService suspended 또는 NEXUS 서비스 중지로 수행하며, 다시 시작하면
새 최신 입력부터 처리한다. 소비자를 완전히 중지하려면 해당 Deployment를 0 replica로
줄인다. 원래 시험 서비스로 되돌릴 때는 먼저 소비자를 중지하고 진행 요청의 종료를 확인한다.

성능 profile, 후보 실측과 제약은 [AI 서비스 공통 운영](../../../../docs/AI-서비스-공통-운영.md)을
따른다. `results/2026-09-14-service-auto-input/`에 원본·측정·자동 왕복·readback을 보관한다.
등록 demo payload는 기록된 센서 값을 재생하는 시험이며 새 현장 관측으로 표시하지 않는다.
