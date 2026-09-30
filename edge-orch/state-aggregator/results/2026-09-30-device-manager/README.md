# Device Manager 운영 배포 — 2026-09-30

기존 운영 현황을 보존하고 Profile/Device Manager를 운영 대시보드에 추가한다.
왼쪽 메뉴는 사용자 확정대로 운영 현황·디바이스 관리 두 개다.

- 기존 이미지: `192.168.0.56:5000/state-aggregator@sha256:6359ca8163aaad7b2c31f77d706cddc10db0a580125c789ed79e86fd2a92d146`
- 후보 이미지: `192.168.0.56:5000/state-aggregator@sha256:712782e162aca26a41e7b2c53b58c137c77e7c70621b6bbba1cc7af85129ef28`
- 빌드: `scripts/build-device-manager-overlay.sh`. 기존 이미지의 운영 현황 자산은 그대로 두고
  관리 기능 10개 파일과 JSON Schema 검증 의존성만 추가한다.
- 보존 파일: `preserved-source-sha256.json`의 9개 파일이 기존 운영 이미지와 byte 단위로 같다.
- 사전 검사: Python 496개 통과. JavaScript 323개 통과, 철회된 로컬 VD prototype 계약 3개 제외.
- 격리 Pod `device-manager-release-check`: `TestClient`를 lifespan 없이 실행해 수집/실행 controller를
  시작하지 않았다. scratch DB와 실제 reader로 nodes=10, sensors=13, sourceErrors={}, writable=true 확인.
- 운영 DB는 기존 PVC `/app/data/device-profile-bindings.sqlite3`를 사용한다. 장비/서비스 실행 원장은 아니다.
- 롤백: Argo CD image override를 기존 immutable digest로 되돌리고 readiness·외부 HTTP를 확인한다.
  Profile metadata DB는 PVC에 보존하며 삭제하지 않는다.

운영 배포·main 통합 결과는 완료 후 아래에 추가한다. 원본 롤백 JSON은 로컬 비공개
`/tmp/device-manager-release-20260930/`에 보관한다. runtime 시험 부하는 생성하지 않는다.

## 운영 검증

- 코드 배포 commit: `a036a778ad6b501c17ab696f617de76833a15989`.
- Argo CD Synced/Healthy, Deployment 1/1 Ready, 위 후보 digest로 rollout 완료.
- API `/api/v1/device-manager`: nodes 10, sensors 13, sourceErrors {}, writable true.
- 기존 로컬 Profile 1개와 Node UID 일치 연결 1개를 운영 API로 이관했다. 원본 노드/센서/실행체 쓰기 없음.
- 운영 Pod에서 보존 파일 9개의 SHA256 일치를 재검증했다.
- 실제 Traefik 브라우저: 운영 현황 유지, 디바이스 관리 메뉴·Profile 수·장비 상세 표시,
  320/390/768/1440px overflow 0. 운영 현황의 기존 점검 항목은 이번 기능 배포로 정상화했다고 주장하지 않는다.
- 시각 근거: `output/playwright/production-overview-before-device-manager.png`,
  `production-device-manager-desktop.png` (로컬 검증 산출물).
- main은 승인된 현재 브랜치 내용을 fast-forward로 통합한다. `[skip ci]`는 과거 55개 커밋의
  다른 스택을 재배포하지 않도록 이번 통합에서만 사용한다. 검증한 dashboard는 Argo CD로 직접 동기화했다.
