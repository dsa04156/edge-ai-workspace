# Edge AI Daylight Operations Interface System

## 방향과 분위기

- 대상: 엣지 AI 플랫폼 운영자. 운영 상태를 열고 10초 안에 장애 대상, 최신 관측,
  영향을 받는 물리 source와 서비스를 식별해야 한다.
- 분위기: 차분하고 정밀한 밝은 산업 운영 화면. 주간 제어실의 무광 패널, 백색 계기판,
  상태 LED에서 가져온 색과 재질을 사용한다.
- 금지: 일반 SaaS의 동일 카드 반복, 장식용 gradient, 강한 초록색 면, 두꺼운 panel
  경계, 상태와 무관한 다색 accent.
- 제품 signature: `물리 source → 관측 트윈 → AI 서비스` 연결을 가는 청록 status rail로
  표현한다. 관측 트윈은 가상 하드웨어나 KubeEdge desired/reported twin이 아니다.

## 색상과 토큰

최종 토큰의 원본은 `edge-orch/state-aggregator/app/static/apple-dashboard.css`다.

| 역할 | 값 | 규칙 |
|---|---:|---|
| Canvas | `#edf2f1` | 전체 배경 |
| Rail | `#edf2f1` | canvas와 같은 청회색 |
| Surface | `#ffffff` | 기본 백색 panel |
| Raised surface | `rgba(246, 249, 248, .98)` | popover·상세 표면 |
| Control | `rgba(20, 54, 57, .06)` | inset control·inactive state |
| Standard line | `rgba(20, 54, 57, .13)` | 조용한 구조 분리 |
| Primary text | `#132e35` | 핵심 상태·수치 |
| Secondary text | `#49616a` | 설명·label |
| Tertiary text | `#60777d` | metadata·timestamp |
| Interaction accent | `#006d77` | 선택·focus·주 동작만 |
| Healthy | `#19724c` | 정상 상태만 |
| Warning | `#946200` | 주의 상태만 |
| Error | `#b83248` | 장애 상태만 |
| Information | `#2769a3` | 링크·정보 상태만 |

- 색상 비율은 중립 60%, 보조 표면 30%, accent와 상태색 10% 이하로 유지한다.
- status 색상은 텍스트·아이콘·배지 상태와 함께 사용하며 색상만으로 의미를 전달하지 않는다.

## 깊이와 표면

- 전략: 백색 surface + 얕은 shadow. Canvas → panel → raised detail의 계층을 유지한다.
- 기본 panel: `12px` radius, `1px` 저대비 line, `0 2px 8px rgba(31,57,60,.04)` shadow.
- control: 주변보다 소폭 짙은 inset fill, `8px` radius.
- mobile panel: `12px` radius.
- sidebar는 canvas와 같은 계열을 사용하고 얇은 오른쪽 line으로만 분리한다.
- `prefers-reduced-transparency`에서는 blur를 제거하고 solid surface를 사용한다.

## 타이포그래피와 위계

- 글꼴: `-apple-system`, `BlinkMacSystemFont`, `Apple SD Gothic Neo`, `Pretendard`,
  `system-ui`, sans-serif.
- 본문 기준은 13–14px의 조밀한 운영 밀도이며 약 1.2 비율로 제목 단계를 만든다.
- 페이지 h1/h2는 `28–32px`, `650–700`, `-0.035em` tracking.
- 운영 수치는 `32–38px`, `650`, `-0.055em`, `tabular-nums`를 사용한다.
- label은 `10–12px`, secondary/tertiary color와 weight 차이로 낮춘다.
- 한 화면의 focal point는 핵심 운영 상태와 수치다. 페이지 제목과 설명은 한 단계 낮춘다.
- heading은 `text-wrap: balance`, 설명은 충분한 line-height를 유지한다.

## 간격과 밀도

- 기본 단위: `4px`.
- 반복 간격: micro `4/8px`, component `12/16px`, section `24/32px`.
- desktop workspace padding: `32px`.
- mobile workspace padding: `18px 16px 32px`.
- control hit area: 기본 `44px`, mobile 탭은 최소 `40px`.
- 관련 정보는 조밀하게 묶고 section 사이에는 24px 이상의 명확한 호흡을 둔다.

## 레이아웃 패턴

- Desktop: `224px` 운영 레일 + command bar + workspace. 운영 개요의 보조 관측 패널은
  `300px`이고 main content에 종속된다. 선택 항목 상세는 기존 modal side sheet를 사용한다.
- `1180px` 이하: 운영 레일을 sticky 가로 스크롤 탭으로 전환한다.
- `760px` 이하: 단일열 workspace, compact header, 가로 스크롤 탭을 사용한다.
- 페이지 전체의 가로 overflow는 허용하지 않는다. 넓은 table/graph만 내부 scroller를 쓴다.

## 재사용 컴포넌트

### 운영 레일 탭

- Desktop `44px` 높이, `8px` radius, `13px/590`.
- inactive는 투명, hover는 control fill.
- active는 백색 surface와 청록 글자로 표시한다.
- Mobile은 `40px` 높이의 가로 탭으로 전환한다.

### 상단 command bar

- `76px` 최소 높이, `14px 24px` padding, blur `22px`.
- 검색은 밝은 inset control이다. 새로고침은 청록 soft fill을 사용하는 보조 주 동작이다.
- Mobile은 제목·새로고침 한 행, 검색 한 행으로 쌓는다.

### 운영 분류 요약

- 하나의 `12px` segmented surface를 사용한다.
- 운영 개요는 desktop 4열(1.2:1:1:1), mobile 2×2이며 segment 사이에 저대비 divider를 둔다.
- 노드·자원 요약은 서버와 현장 엣지 노드의 2분류다.

### Panel

- `12px` radius, white surface, shallow shadow. 운영 개요 panel의 외곽선은 생략하고 내부 관계는 divider로 표시한다.
- nested content는 더 밝은 동일 계열 surface 또는 divider로만 구분한다.
- 경고 panel은 panel 전체를 상태색으로 채우지 않고 indicator·label에만 상태색을 쓴다.

### 물리 source → 관측 트윈 → 서비스 row

- 연결된 row의 시작점에 `2px` 청록 rail을 사용한다.
- inventory 상단에는 연결 흐름을 암시하는 얇은 청록 line을 둘 수 있다.
- service binding은 N:M을 지원하며 상태, 연결 여부, freshness를 하나의 값으로 합치지 않는다.

### Button과 form control

- 기본 높이 `44px`, control radius `8px`.
- hover는 색과 표면만 미세하게 변하고, active는 `scale(.97)`을 사용한다.
- focus는 `0 0 0 3px rgba(0,109,119,.2)`.
- native button/input/select/details 의미와 keyboard 동작을 유지한다.
- `transition: all`은 금지하고 속성을 명시한다.

## 모션과 접근성

- 화면 진입은 최대 `260ms`, `opacity + translateY(6px)`만 사용한다.
- 반복 동작에는 장식 모션을 추가하지 않는다.
- `prefers-reduced-motion`에서는 이동과 animation을 제거한다.
- `prefers-reduced-transparency`에서는 solid surface를 사용한다.
- `prefers-contrast: more`에서는 line과 보조 text 대비를 높인다.
- 모든 interactive control은 hover, active, focus, disabled 상태를 가져야 한다.

## 적용 규칙

- 새 화면을 만들기 전에 이 파일과 `apple-dashboard.css`를 읽는다.
- native control과 데이터 권위·상태 판단 계약을 유지한다. 메뉴·DOM 변경은 승인된 정보 구조를 따른다.
- 새 색상·radius·spacing을 임의로 추가하지 않고 위 토큰과 4px grid를 먼저 재사용한다.
- 반복 컴포넌트의 측정값이 바뀌면 구현과 이 파일을 함께 갱신한다.
- 최종 화면은 desktop과 390px mobile에서 직접 확인한다.

## 2026-09-07 승인 시안 적용

- 주 메뉴: 운영 개요, 디바이스·서비스 연결, AI 서비스, 노드·자원, 장비 연결·관리, 서비스 설계. 기존 별도 시험 메뉴는 분리 보존한다.
- 운영 개요의 초점: 우선 점검 → source/관측 트윈/서비스 연결 → 근거 상세. 기존 서버 자원 요약과 기술 지표는 노드·자원으로 이동한다.
- 운영 개요 4분류 요약은 desktop 1.2:1:1:1, mobile 2×2다. 주 영역과 보조 관측 패널은 desktop minmax(0,1fr):300px, 1180px 이하 단일열이다.
- 레일 활성 항목은 백색 배경과 청록 글자, 그림자 없는 상단바와 44px 검색·버튼을 사용한다.
- 새 overview 패널은 불투명 백색, 12px radius, 24px padding과 gap, 얕은 shadow다. 모바일 padding은 16–20px다. 기존 관리·설계의 내부 밀도는 유지한다.
- 연결 행은 세 대상과 얇은 청록 화살표를 유지하고 모바일에서 세로로 쌓는다. 원본 ID와 API reason은 줄바꿈하며 생략만으로 숨기지 않는다.
- API 실패 시 대시보드 notice와 이전 관측 시각을 표시한다. 요약은 0 대신 —, 바인딩 관측 실패는 미연결 대신 관측 불가다.

## 2026-09-07 NEXUS 과제 전체 작업 공간

위 운영 UI 규칙은 `/classic`과 재사용 내부 도구에 적용한다. 기본 진입점 `/`의 NEXUS는 과제 전체 구조를 기준으로 새로 설계한 별도 시스템이다.

- 기준 구현: `edge-orch/state-aggregator/app/static/nexus/platform.css`.
- 6개 영역: 플랫폼 개요, 디바이스·트윈, 서비스·워크플로우, 자원·배치, 데이터·복구, 실증·성능.
- 3개 관점: 실제 관측 / 목표 시스템 / 현재 구현 근거. 실측값·목표·문서 근거를 같은 상태색으로 합치지 않는다.
- 배경 `#f3f5f7`, 표면 `#fff`, 본문 `#202d3e`, 보조 `#637084`, 선 `#dce2e9`, 강조 `#315fbc`, 활성 레일 `#223248`.
- 물리 `#257e80`, 논리 실행체 `#7966b1`, 연산 `#315fbc`는 객체 계층을 나타낸다. 경고 `#996922`, 정상 `#357855`는 별도 상태 의미다.
- desktop 레일 220px, 패널 radius 12px, 기본 글꼴 Pretendard/한국어 시스템 폴백 14px. 작은 데이터 표는 행별 원 식별자와 관측 시각을 보존한다.
- 기존 도구는 같은 출처 iframe 안에 두고 원래 탐색 chrome만 숨긴다. 상위 자동 갱신은 열린 도구를 교체하지 않는다. 내부 form, validation, 권한 계약은 유지한다.
- 도구 프레임: 폭 100%, 높이 `calc(100dvh - 140px)`, 최소 640px, 모바일 최소 720px. 내부 스크롤로 기존 긴 관리 절차와 캔버스를 유지한다.
- 실제 관측의 제목은 확인·검토 동작을 설명한다. 목표 시안의 실행·복구 표현을 운영 완료 주장으로 재사용하지 않는다.

### 가상 디바이스 운영 사이클 (2026-09-08)

- 고정된 등록 정의 → 실행체 시작 → 시험 요청 → 정지·반환의 4단계 표시를 사용한다. desktop 4열, mobile 2열이며 12px gap, 14px padding, 8px radius다.
- 실행 제어 패널은 백색·12px radius·24px padding(모바일16px). 시작/시험은 NEXUS 강조색 `#315fbc`, 정지는 중립 버튼이다.
- 4개 입력은 desktop4열/mobile2열, 최소 높이44px. 부모 주기 갱신으로 입력 값·토큰·요청 키를 지우지 않는다.
- 접수 문구와 실제 관측 상태를 나란히 두며 응답 유실을 성공으로 표시하지 않는다. 재전송은 같은 키를 유지하는 별도 버튼이다.
- 결과는 영속된 과거 영수증으로 표시한다. 원시 identity/hash는 접은 상세에 두고 모델 결과·시각을 먼저 보인다.

### 물리 장비에서 기능·서비스로 탐색 (2026-09-08)

- 실제 디바이스 화면의 초점은 물리 source 선택이다. 청록 physical 토큰의 선택 버튼에서 장비 → 등록 기능/관측 트윈 → 이용 서비스 흐름으로 이어진다.
- 장비 선택 버튼은 최소108px, padding16px, gap12px, radius8px. 선택 상태는 physical-soft 표면과 왼쪽3px 표시 및 aria-pressed로 드러낸다. 모바일은 한 열이다.
- 기능은 native details/summary로 펼친다. 최초에는 첫 기능만 열고 사용자의 펼침 상태를 갱신·검색 중 유지한다. 요약은 최소84px, 상세는 padding20px(모바일16px), 왼쪽2px physical 선, radius8px. 최근 관측값 / 트윈 / 이용 서비스의 3열, 1150px 이하2열, 700px 이하1열이다. 값20px, 기능 제목14px, 원 식별자와 시각10–12px를 사용한다.
- 장비별 서비스 요약은 기능 행 뒤에 두며 독립 실행 기능 시험은 마지막 중립 표면에 둔다. 기능 검색과 주기 갱신은 선택 장비·형제 기능·키보드 focus를 유지한다.


### 통합 서비스 운영 연결 (2026-09-08)

- 기존 NEXUS 토큰을 유지하며 8개 메뉴는 운영 현황/디바이스/데이터/AI 서비스/서비스 제작/자원·오프로딩/장애·이력/검증·설정이다. 기존 classic 관리·설계 작업 공간을 재사용한다.
- 서비스의 Input→Alignment→Features→Inference→Result를 desktop 가로 흐름, 700px 이하 세로 흐름으로 표시한다. 단계 표면은 16px padding, 190px 최소폭, 위쪽 3px compute 선이다.
- Configured 위치와 Observed Pod·node를 분리하고 세부 자원은 native details로 펼친다. 공유 workload 지표를 독립 stage 계측으로 표시하지 않는다.
- 서비스 품질은 4열 definition list, 모바일 2열이다. 수치는 18px/650, label 12px, 간격16px, 섹션24px를 사용한다.
- Data Explorer는 resource별 세로축과 공통 시간축을 사용하며 표본 점만 표시한다. 선으로 결측 구간을 이어 붙이지 않는다.
- 서버 설계 저장 controls는 기존 canvas 밖의 접힌 details에 두며 viewport·local draft·관리 토큰 입력을 polling으로 교체하지 않는다.

### 물리 장비의 가상 디바이스 (2026-09-08)

- 디바이스 화면은 물리 장비와 가상 디바이스를 별도 탭으로 선택한다. 가상 표현은 기존 virtual/virtual-soft 토큰, 원본은 physical/physical-soft 토큰으로 구분한다.
- 가상 선택 카드는 논리 ID와 원본 ID를 함께 표시하며 최대460px, padding16px, radius8px다. 선택은 aria-pressed와 왼쪽3px 선으로 표시한다.
- 상세는 원본 → 가상 표현 연결을 1fr/32px/1fr 구조로 표시하고 모바일은 세로로 쌓는다. 원본 이동과 가상 디바이스 열기는 최소44px 버튼이다. 제공 기능은 기존 펼침 패턴을 재사용한다.

### 운영 상태 가독성 보정 (2026-09-08)

- NEXUS 본문·표 15–16px, 메뉴 15px, 보조 정보 최소13px, 서비스 요약 제목26px(모바일23px).
- 서비스 요약은 AI 처리 여부 → 중단/미확인 이유 → 센서 수신 → 오프로딩 적용 여부 → 최근 결과 시각 순이다.
- Pod Ready는 AI 처리 근거가 아니다. 단계는 배포 노드·준비된 Pod를 명시하고 상세 실행체·원본 상태·자원 근거는 펼쳐 본다.
- 단계 흐름은 넓은 화면에서 5열에 맞추고 1150px 이하에서는 세로로 연결한다. 원 식별자는 줄바꿈으로 보존한다.
- 상태 code는 data-state에 유지하면서 한국어 설명을 표시한다. 현재 관측이 없으면 중단/정상 모두 단정하지 않는다.

### 서비스 배치 지도 (2026-09-08)

- AI 서비스의 기본 관측은 장비 안에 워크로드 카드를 두는 배치 지도다. 현장:서버 2:1, 1100px 이하 1:1, 700px 이하 세로 배치다. 빈 노드는 선택적으로 표시한다.
- 노드 표면은 기존 NEXUS white/line, 12px radius, 내부 12–16px 간격이다. 서비스/수집/증강의 3px 좌측 선은 accent/physical/virtual 토큰을 사용한다.
- Pod 준비와 서비스 처리 권한을 별도 배지로 둔다. 카드 선택은 accent-soft, 관련 서버 실행체는 virtual-soft로 표시한다.
- 실제 관측과 별도 예시는 배너와 예시 장비명으로 구분한다. 카드 위치 변화 260ms, 결과 증가는 유한 강조만 사용하고 reduced-motion에서는 이동을 제거한다.
