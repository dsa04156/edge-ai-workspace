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
