#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
이 스크립트는 폐기되었습니다.

과거 telemetry namespace의 Device Service -> 중앙 MessageBus 직접 수집 경로를
재생성하지 마십시오. 현재 운영 진입점은 edgex/k8s이며 다음 경로를 배포합니다.

  Protocol Adapter -> edge-telemetry-agent -> SQLite outbox
  -> HTTPS/mTLS -> ingest gateway -> EdgeX Core Data/PostgreSQL

실행 절차는 docs/ops/현재-데모-운영-절차.md를 따르십시오.
EOF

exit 64
