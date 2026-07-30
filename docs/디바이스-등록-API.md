# 디바이스 발견 및 등록 API

> 기준 구현: `edgex/adapter-controller/app/api.py`
> OpenAPI: Adapter Controller `/docs`, `/openapi.json`

## 접근 경계

`/api/v1/*`와 `/internal/v1/*`는 Adapter Controller의 cluster-internal API다. 모든 요청은
다음 HMAC header를 사용한다.

```text
X-Controller-Timestamp: Unix seconds
X-Controller-Signature: hex(HMAC-SHA256(secret, canonical))

canonical =
  timestamp + "\n" +
  HTTP_METHOD + "\n" +
  URL_PATH_WITHOUT_QUERY + "\n" +
  SHA256(raw_body)
```

서명 허용 시간은 기본 60초다. 브라우저는 이 key를 가지지 않으며
`state-aggregator`의 `/management/*` BFF를 사용한다. mutation API는
`ADAPTER_RUNTIME_MUTATION_ENABLED=true`와
`ADAPTER_DEVICE_DISCOVERY_ENABLED=true`일 때만 열린다.

오류 body는 기존 내부 API 호환을 위해 FastAPI `detail`을 유지하고, 기계 판독 코드는
`X-Error-Code` 응답 header로 제공한다.

| HTTP | `X-Error-Code` | 의미 |
|---|---|---|
| 401 | `INTERNAL_SIGNATURE_INVALID` | HMAC 또는 timestamp 오류 |
| 404 | `RESOURCE_NOT_FOUND`, `FEATURE_DISABLED` | 대상 없음 또는 기능 비활성 |
| 409 | `STATE_CONFLICT` | 상태 전이 또는 idempotency 충돌 |
| 422 | `REQUEST_NOT_ALLOWED` | Catalog, node, presence 또는 요청 검증 실패 |
| 502 | `BACKEND_OPERATION_FAILED` | Kubernetes/EdgeX/저장소 backend 오류 |

## Candidate API

### 목록

```http
GET /api/v1/discovery/candidates
```

query:

- `protocol`: `serial`, `i2c`, `mqtt`, `modbus`, `opcua`, `onvif`, `rtsp`, `rest`
- `nodeId`
- `state`
- `presence`: `present`, `stale`, `declared`
- `page`: 기본 1
- `pageSize`: 기본 100, 최대 500

응답:

```json
{
  "items": [
    {
      "candidateId": "candidate-<sha256>",
      "source": "node-scan",
      "nodeName": "etri-dev0001-jetorn",
      "protocol": "serial",
      "transport": "usb-serial",
      "displayName": "Arduino Uno",
      "devicePath": "/dev/serial/by-id/usb-Arduino-...",
      "hardwareId": "75035303230351E0D171",
      "recommendedProfile": "arduino-multisensor-v1",
      "matchConfidence": "exact",
      "state": "PENDING_APPROVAL",
      "authState": "not_checked",
      "presence": "present",
      "packageState": "registration-ready",
      "registrationReady": true,
      "retryCount": 0,
      "transitionCount": 3
    }
  ],
  "total": 1,
  "page": 1,
  "pageSize": 100
}
```

### 단건

```http
GET /api/v1/discovery/candidates/{candidateId}
```

### 수동 Modbus 개발 후보 선언

브라우저는 `POST /management/discovery/manual` BFF를 사용하고, BFF는 다음 내부 API를
HMAC으로 호출한다.

```http
POST /internal/v1/discovery/manual
Content-Type: application/json

{
  "candidate": {
    "nodeName": "etri-dev0001-jetorn",
    "protocol": "modbus",
    "transport": "modbus-tcp",
    "displayName": "EdgeX Modbus TCP simulator",
    "properties": {
      "Mode": "tcp",
      "Host": "edge-modbus-simulator.edgex-edge.svc.cluster.local",
      "Port": 1502,
      "UnitID": 1
    }
  },
  "requestRef": {
    "requestId": "<64 lowercase hex>",
    "payloadHash": "<64 lowercase hex>"
  }
}
```

서버는 `Mode`, `Port`, `UnitID`를 정규화하고 node/protocol/endpoint property로 stable
candidate ID를 만든다. 현재 Git Catalog와 위 값이 정확히 일치할 때만
`PENDING_APPROVAL`과 `registrationReady=true`가 된다. 다른 host/port/unit ID와 실제 PLC
endpoint는 검증된 별도 binding이 없으므로 `BLOCKED`다. 이 API는 네트워크를 scan하지 않고,
비밀번호·token·URL userinfo가 있는 property는 거부한다.

### 승인

```http
POST /api/v1/discovery/candidates/{candidateId}/approve
Content-Type: application/json

{
  "actor": "operator-1",
  "reason": "현장 장비 라벨과 설치 기록 확인",
  "requestRef": {
    "requestId": "<64 lowercase hex>",
    "payloadHash": "<64 lowercase hex>"
  }
}
```

승인 API는 즉시 전체 등록을 동기 실행하지 않는다. 성공 응답의 첫 상태는 `APPROVED`이고
Controller reconciliation이 `SERVICE_READY`, `METADATA_REGISTERED`,
`EVENT_CONFIRMED` 순서로 진행한다. 같은 `requestId`와 `payloadHash`를 반복하면 최초 응답을
재생하며 중복 Device를 만들지 않는다. 같은 request ID를 다른 hash로 재사용하면 409다.

승인은 다음 경우 거부된다.

- 후보가 승인 가능한 상태가 아님
- `presence=stale`
- Device Catalog exact match가 아님
- 실행 Runtime image가 allowlist digest와 다름
- 외부 인증이 거절되거나 unavailable

### 거절

```http
POST /api/v1/discovery/candidates/{candidateId}/reject

{
  "actor": "operator-1",
  "reason": "승인되지 않은 시험 장비",
  "requestRef": {
    "requestId": "<64 lowercase hex>",
    "payloadHash": "<64 lowercase hex>"
  }
}
```

`PENDING_APPROVAL`, `BLOCKED`, `FAILED`에서만 `REJECTED`로 이동한다.

### 등록 재시도

```http
POST /api/v1/discovery/candidates/{candidateId}/retry

{
  "actor": "operator-1",
  "reason": "Device Service 설정 수정 완료",
  "requestRef": {
    "requestId": "<64 lowercase hex>",
    "payloadHash": "<64 lowercase hex>"
  }
}
```

`FAILED` 상태에서만 허용한다. Catalog와 인증을 다시 확인하고 attempt/retry count를
증가시킨다. 이전 attempt의 Controller 소유 리소스 rollback이 끝나지 않았으면 재시도를
차단한다.

외부 인증 `unavailable` 또는 `error`로 `BLOCKED`된 후보는 새 승인 요청을 보내 인증을
재확인할 수 있다. 명시적 `denied` 후보는 자동 재승인하지 않는다.

## Reconciliation과 Plan

### 수동 reconciliation

```http
POST /api/v1/discovery/reconcile

{
  "nodeId": "etri-dev0001-jetorn",
  "protocol": "serial"
}
```

두 필드는 선택 사항이다. candidate freshness와 진행 중인 Registration Saga를 다시
평가한다. 이 API가 Plan에 없는 네트워크 scan을 새로 시작하지는 않는다.

### Plan 조회

```http
GET /api/v1/discovery/plans/{nodeId}
GET /internal/v1/discovery/plans/{nodeId}
```

두 번째 경로는 Discovery Agent가 사용한다. 등록되지 않은 Kubernetes node는 422다.

### Plan 변경

```http
PUT /api/v1/discovery/plans/etri-dev0001-jetorn

{
  "nodeId": "etri-dev0001-jetorn",
  "serial": {
    "enabled": true,
    "allowedVidPid": ["2341:0043"],
    "baudRates": [115200],
    "manifestProbeEnabled": false,
    "manifestCommand": "WHOAMI",
    "manifestTimeoutSeconds": 1.5
  },
  "i2c": {
    "enabled": false,
    "buses": [],
    "allowedAddresses": [],
    "activeProbeEnabled": false,
    "identificationRules": []
  },
  "modbusRtu": {"enabled": false, "endpoints": [], "cidrs": [], "unitIds": []},
  "modbusTcp": {"enabled": false, "endpoints": [], "cidrs": [], "unitIds": []},
  "opcua": {"enabled": false, "endpoints": []},
  "onvif": {"enabled": false, "cidrs": []},
  "mqtt": {
    "enabled": false,
    "discoveryTopic": "edge/discovery/+/+"
  },
  "version": 1
}
```

서버가 저장 시 version과 `updatedAt`을 갱신한다. Plan은 PVC의 SQLite에 남아 재시작 후
복구된다. 기본 파일은 해당 node의 Plan이 없거나 파일의 version이 저장된 version보다
높을 때만 seed/upgrade한다. 같거나 낮은 파일 version은 운영 중 저장된 Plan을 덮어쓰지
않는다.

Sense HAT v1처럼 여러 I2C chip이 한 물리 장비를 구성하면 한 rule의 `identities`에
허용 address/register/expected 값을 모두 선언한다. 모든 check가 일치해야 후보 하나를
만들며 일부만 일치하면 후보를 만들지 않는다.

## Registration과 audit

### 등록 진행 조회

```http
GET /api/v1/registrations/{candidateId}
```

예:

```json
{
  "candidateId": "candidate-<sha256>",
  "status": "METADATA_REGISTERED",
  "step": "WAITING_FIRST_EVENT",
  "attempt": 1,
  "bindingId": "jetson-arduino-multisensor-v1",
  "runtimeName": "device-serial-jetson",
  "serviceName": "device-serial-jetson",
  "profileName": "arduino-multisensor-v1",
  "deviceName": "arduino-75035303230351e0d171-<identity10>",
  "createdRuntime": false,
  "createdProfile": true,
  "createdDevice": true,
  "eventNotBefore": "2026-07-24T00:00:00Z",
  "eventDeadline": "2026-07-24T00:01:00Z"
}
```

`reuse-existing` Catalog binding의 응답은 `createdRuntime`, `createdProfile`,
`createdDevice`가 모두 `false`일 수 있다. 이는 등록을 생략했다는 뜻이 아니라 기존
Runtime/Profile/Device의 실제 image와 Metadata shape를 검증했고, `eventNotBefore` 이후
첫 Event까지 확인한다는 뜻이다. decommission이나 rollback도 이 기존 리소스를 삭제하지
않는다.

### Catalog 조회

```http
GET /api/v1/catalog/bindings
```

유효한 binding과 격리된 invalid binding 오류를 함께 반환한다. API로 새 image를 추가하는
기능은 없다.

### audit 조회

```http
GET /api/v1/discovery/events?candidateId={candidateId}&limit=200
```

발견, 상태 전이, 승인, 거절, 차단, Plan 변경과 실패 원인을 최신순으로 반환한다.

## 기존 대시보드 BFF 호환

대시보드는 다음 기존 경로를 유지한다.

- `GET /management/discovery`
- `POST /management/discovery/manual`
- `PATCH /management/discovery/{candidateId}`
- `DELETE /management/discovery/{candidateId}`
- `POST /management/discovery/{candidateId}/decommission`

`accepted` PATCH는 승인 Saga를 시작하고 `FAILED` 후보에서는 retry로 해석한다.
`ignored` PATCH는 reject다. 등록된 후보는 별도 decommission workflow 없이 삭제할 수 없다.
decommission은 `X-Confirm-Candidate`의 exact candidate ID와 사유를 요구하며 Controller가
소유한 리소스만 정리한다. node-scan 장비가 계속 연결돼 있으면 다음 report에서 같은
candidate ID가 `PENDING_APPROVAL`로 다시 나타나고, 자동 재등록하지 않는다.
현재 PoC BFF는 운영자 Bearer token이나 `decisionAuthenticationRequired` 필드를 제공하지
않는다. 후보 결정, 수동 후보 생성·삭제, Runtime, Device와 connection mutation은 모두
요청별 `Idempotency-Key`를 요구하고 browser `Authorization` header 없이 동작한다.
state-aggregator가 Adapter Controller로 보내는 내부 요청은 계속 HMAC으로 서명한다.
외부 AuthProvider의 승인도 후보 장비 신뢰 검증 단계로 유지되지만 운영자 인증은 아니다.
따라서 이 BFF는 접근이 제한된 개발 테스트베드용이며 운영 노출 전 별도 사용자
인증·인가를 앞단에 추가해야 한다.

## 대시보드 Device Profile BFF

대시보드의 `디바이스 프로필` 영역과 `프로필 생성` 대화상자는 Adapter Controller가 아니라 `state-aggregator`가
Core Metadata와 직접 통신하는 다음 BFF를 사용한다. 브라우저 `Authorization` header는
사용하지 않으며 생성 요청만 `Idempotency-Key`를 요구한다.

### Profile 목록

```http
GET /management/profiles
```

Core Metadata Profile의 이름, 설명, 제조사, 모델, label과 resource 수를 이름순으로
반환한다. 웹에서 생성한 Profile은 등록 현황의 프로필 영역에 즉시 표시하며, 전체
Profile은 `장비 연결` 3단계 선택 목록에 제공한다.

### Profile 검증

```http
POST /management/profiles/validate
Content-Type: application/json

{
  "name": "arduino-environment-v1",
  "description": "Arduino 환경 센서 읽기 계약",
  "manufacturer": "Arduino",
  "model": "uno-environment-v1",
  "labels": ["serial", "environment"],
  "resources": [
    {
      "name": "temperature",
      "valueType": "Float64",
      "units": "Cel",
      "description": "온도"
    },
    {
      "name": "humidity",
      "valueType": "Float64",
      "units": "percent",
      "description": "상대 습도"
    }
  ]
}
```

허용 value type은 `Bool`, signed/unsigned `Int8`~`Int64`, `Float32`,
`Float64`, `String`이다. resource는 1~64개이며 이름은 Profile 안에서 고유해야 한다.
이 API는 mutation을 수행하지 않는다. 같은 이름의 Profile이 다른 resource 계약으로
존재하면 `valid=false`, `profile_name_conflict`를 반환한다. 동일 계약이면 재사용
warning을 반환한다.

### Profile 생성

```http
POST /management/profiles
Idempotency-Key: profile-create-<unique-request>
Content-Type: application/json

{same payload as validation}
```

서버는 모든 resource를 `readWrite=R`로 만들고 `edge-ai-web-managed` label을 추가한다.
생성 뒤 Core Metadata readback의 이름·설명·제조사·모델과 resource
`name/valueType/readWrite/units` 계약을 다시 비교한다. readback이 다르면 이번 요청이
새로 만든 Profile만 rollback한다. 기존 Profile은 삭제하지 않는다.

대표 응답:

```json
{
  "requestId": "<64 lowercase hex>",
  "payloadHash": "<64 lowercase hex>",
  "name": "arduino-environment-v1",
  "created": true,
  "status": "created",
  "profile": {
    "name": "arduino-environment-v1"
  }
}
```

`status=existing`은 동일 계약의 기존 Profile을 재사용했다는 뜻이다. Profile 생성은
parser, Device Service image, raw device path, Catalog binding, Device와 command를
생성하지 않는다. 따라서 발견 후보의 승인 조건은 그대로이며 Profile만 만든 후보를
`registration-ready`로 간주하지 않는다.

## 대시보드 통합 연결 BFF

대시보드의 보이는 신규 등록 진입점은 `장비 연결` 하나다. 사용자가 마지막
`검증하고 연결`을 누르면 브라우저가 같은 payload로 다음 두 API를 순서대로 호출한다.

```http
POST /management/connections/validate
POST /management/connections
Idempotency-Key: connection-<unique-request>
```

첫 API는 mutation 없이 Runtime plan과 EdgeX 변경을 검증한다. 검증이 성공한 경우에만 두
번째 API가 기존 Device Service 재사용 또는 검증 template 배포, Profile/Device readback과
first Event 확인을 시작한다. 브라우저에는 `reuse`/`deploy` 선택을 노출하지 않고
`runtime.mode=auto`를 사용한다.

MQTT 개발 package의 대표 요청은 다음과 같다.

```json
{
  "adapterId": "mqtt",
  "runtime": {
    "mode": "auto",
    "targetNode": "etri-dev0001-jetorn",
    "hardwareBindingId": "jetson-mqtt-network-001",
    "settings": {
      "Broker": "mqtt://edge-mqtt-simulator.edgex-edge.svc.cluster.local:1883",
      "IncomingTopic": "incoming/data/#",
      "Qos": 0
    }
  },
  "device": {
    "name": "mqtt-temperature-sim-001",
    "description": "MQTT 개발 온도 센서",
    "labels": ["mqtt", "temperature", "development-fixture"],
    "tags": {"nodeName": "etri-dev0001-jetorn"},
    "protocolProperties": {
      "CommandTopic": "command/mqtt-temperature-sim-001",
      "ResourceName": "temperature"
    },
    "adminState": "UNLOCKED"
  },
  "profile": {
    "mode": "create",
    "name": "edgeai-mqtt-temperature-v1",
    "description": "검증된 EdgeX MQTT Device Service의 읽기 전용 온도 데이터",
    "manufacturer": "ETRI",
    "model": "edgeai-mqtt-temperature-v1",
    "labels": ["mqtt", "temperature", "read-only", "edge-ai-web-managed"]
  }
}
```

`runtime.settings`는 adapter별 Catalog schema를 따르며 Controller가 다시 검증한다.
알 수 없는 key, Secret 성격의 이름, URL userinfo, 허용하지 않은 scheme/host/CIDR,
topic pattern과 QoS는 `422`로 거부한다. 설정을 정규화한 hash가 같은 Runtime만 재사용하므로
다른 broker를 기존 Device Service에 잘못 연결하지 않는다.

작업 상태는 다음 API로 조회한다.

```http
GET /management/connections/operations/{requestId}
```

정상 순서는 `RUNTIME_REQUESTED → RUNTIME_READY → PROFILE_APPLIED →
DEVICE_APPLIED → WAITING_EVENT → ACTIVE`다. `ACTIVE`는 Core Metadata 등록만이 아니라
첫 Core Data Event까지 확인했다는 뜻이다. 연결 가능한 범위는 Catalog에 검증 package가
있는 protocol뿐이며, API가 임의 image나 새로운 driver를 생성하지 않는다.
