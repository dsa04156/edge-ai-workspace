# Profile v1 명세와 웹 연결

> 2026-09-30 · v1 초안. Schema·예제·검증·읽기 전용 관측을 구현했다.
> DeviceProfile 등록·장비 연결은 [디바이스 매니저](디바이스-매니저.md)의 로컬 metadata 저장소로 확장했다.
> Service/VirtualDevice Profile 등록·자동 배치·Workflow 실행·VD 동적 생성은 후속 단계다.

장비의 능력표와 서비스의 요구사항표를 먼저 맞춘다. 웹의 별도 **프로파일** 화면은 사용자 요청으로
제거했고, **기존 NEXUS 왼쪽 메뉴의 디바이스 관리**에서 DeviceProfile을 관리한다.
기존 디바이스와 별도 페이지이며 장비 데이터 조회는 유지한다. 네 가지 Schema와 검증·관측·제한 비교 API는 개발 기반으로 보존한다.
ServiceProfile 비교 API는 architecture와 예약 여유만 비교하며 실제 실행 자격을 부여하지 않는다.

## 원본과 배포 패키지

| 경로 | 역할 |
|---|---|
| `schemas/*.schema.json` | 네 가지 JSON Schema Draft 2020-12 원본 |
| `examples/*.json` | 형식 확인용 예제. 검증된 사양·모델·실행 이미지가 아님 |
| [기존 필드 대응표](기존-필드-대응표.md) | 원본·변환·알 수 없는 항목의 경계 |
| `build_bundle.py` | 기존 dashboard Docker context에 Schema·예제를 묶는 생성기 |
| `../edge-orch/state-aggregator/app/profile_spec.py` | 값 간 비교 검증·관측 adapter·읽기 전용 비교 API |

`app/config/profile_spec_v1.json`은 생성물이다. 직접 수정하지 않는다.
Docker와 기존 amd64 OCI 빌드는 같은 생성물을 포함한다. 회귀 테스트는 원본과 bundle의 일치를 확인한다.

```bash
rtk proxy python3 profile-spec/build_bundle.py
rtk proxy python3 profile-spec/build_bundle.py --check
cd edge-orch/state-aggregator
rtk proxy .venv/bin/python -m pytest -q tests/test_profile_spec.py
rtk proxy node --test tests/test_nexus_profiles.js
```

기존 NEXUS UI의 로컬 검증 앱은 저장소 루트에서 실행한다. 수집·실행 제어기를 시작하지
않고 기존 대시보드의 운영 GET과 장비 원본을 읽는다. 저장 경로와 상세 계약은 [디바이스 매니저](디바이스-매니저.md)를 따른다.

```bash
rtk proxy bash edge-orch/state-aggregator/scripts/run-device-manager-preview.sh
```

사용자 요청으로 `0.0.0.0:8768`에서 수신한다. 같은 네트워크에서는
`http://192.168.0.56:8768/`, 서버 안에서는 `http://127.0.0.1:8768/`로 접속한다.
후속 사용자 승인으로 기존 운영 현황을 보존한 운영 웹 배포와 main 통합을 진행한다. 최신 결과는
[현재 구현 상태](../docs/현재-구현-상태.md)를 따른다.

## 명세 규칙

- `apiVersion: edgeai.etri/v1`, `metadata.name/version`을 사용한다. 관측 instance는 별도 ID와
  `profileRef.name/version`을 갖는다. `observed-*`는 알려진 정적 내용의 hash이며 등록된 Profile ID가 아니다.
- DeviceProfile은 정적 Capacity·Capability다. 수집되지 않은 hardware capacity와 지원 runtime은
  `null`이며 물리/가상 여부를 확인하지 못한 노드의 type은 `unknown`이다. `[]`와 `{}`는 알려진 빈 목록/집합이고 `null`과 구분한다.
- ServiceProfile은 장비명을 나열하지 않는다. `runtime.variants`의 architecture·framework·backend·
  image digest·modelArtifact·가속기 조건을 **조합별로** 정의한다. architecture 표준 표기는 `amd64`/`arm64`다.
  조합을 선언해도 artifact 접근·runtime 호환성·모델 실행·성능 qualification이 검증되지는 않는다.
- CPU는 cores, 메모리는 `Ki/Mi/Gi/Ti`, 선택 network 요구량은 `bandwidthMbps` 단위다. minimum은 필수이며 recommended/maximum 미확정은
  `null`이다. 정의한 자원은 `minimum ≤ recommended ≤ maximum`이어야 한다. 웹 API는 Schema 검증에
  더해 서로 다른 단위의 수치 순서·양수 메모리·지연 목표/최대·variant 이름 중복을 검사한다.
- RuntimeState의 `reservation`은 Kubernetes allocatable·Pod requests·그 차이다.
  Prometheus 사용량은 `utilization`에 별도 원래 관측 시각과 함께 둔다. 60초 초과·미래 시각·미수집은
  사용률 판단을 보류한다. Kubernetes Ready는 runtime/model 실행 준비와 다르다.
- 가속기 메모리의 `memoryMode: shared`는 호스트 RAM과 합산하지 않는다. 현재 adapter는 GPU 물리
  capacity나 runtime 지원을 추정하지 않는다. VD와 서버 용량도 합산하지 않는다.
- VirtualDeviceProfile의 emulation·dynamic binding·lifecycle은 선언만 검증한다. 현재 지원 기능이나
  기존 서버 슬롯 규칙의 변경이 아니다. 물리 기능/인터페이스와 서비스 UID 슬롯 관계는 별도 확정한다.

JSON 예제는 YAML에서도 읽을 수 있는 문서다. 별도 YAML Schema를 중복 관리하지 않는다.
웹 편집은 JSON으로 시작하며 YAML 업로드·입력 폼·참조 존재 검증·등록 버전 관리는 후속이다.

## 웹/API 사용

NEXUS `/#profiles`에서 다음 흐름을 사용한다.

1. 명세 종류 선택 → 예제 수정 → **명세 검증**.
2. **현재 장비 관측**에서 실제 node·예약 여유·관측 문서 확인.
3. ServiceProfile → **현재 장비와 비교** → 조건 미충족/추가 검증 사유 확인.
4. **JSON 내려받기**로 현재 입력 보관. 새로고침하면 브라우저 초안은 사라진다.

| API | 기능 |
|---|---|
| `GET /api/v1/profile-spec` | Schema·예제 catalog |
| `GET /api/v1/profile-spec/observations` | 기존 Kubernetes/Prometheus의 읽기 전용 변환 |
| `POST /api/v1/profile-spec/validate` | 64 KiB 이하 JSON 형식·값 검증; 저장하지 않음 |
| `POST /api/v1/profile-spec/compare` | ServiceProfile과 새로 읽은 노드 관측의 제한 비교 |

이 검증 도구에는 Registry CRUD가 없다. DeviceProfile 버전 등록·조회·삭제와 노드 연결은
별도 [디바이스 매니저 API](디바이스-매니저.md)에서 제공한다. 현재 경로를 나눠 등록 API로
오해하지 않게 했다. 원본 조회 실패는 빈 정상 목록과 구분한다. 비교 결과는 항상
`executionAllowed: false`이며 runtime·모델·성능 및 taint/affinity 등 전체 배치 판단을 대신하지 않는다.
정리한 데모를 재등록하거나 요청 부하를 만들지 않는다.

## 검증과 다음 작업

Schema·예제 일치, 잘못된 kind·장비명 필드·수량·tier 역전·오래된 지표·비교 사유·출처 실패·
입력 제한·RFC3339 관측 시각·참조 버전과 UI escaping을 테스트한다. 실제 배포 상태와 브라우저 근거는
[현재 구현 상태](../docs/현재-구현-상태.md)에 기록한다.

실장비 정적 사양과 새 AI 서비스의 검증된 요구량을 보강한다. Device↔Profile 참조 등록은
② 디바이스 매니저의 로컬 범위로 구현했다. 그 뒤 Workflow Task가 ServiceProfile 버전을 참조하도록 연결한다.
