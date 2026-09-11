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

### 서비스 배치 지도 UX 보정 (2026-09-08)

- 서비스 작업 공간은 제목1개, 탭·운영 도구1행, 지도 필터1영역으로 구성한다.
- 지도와 선택 상세는 minmax(0,1fr):320px, 간격20px이며 900px 이하 단일열이다. 원본 식별자는 상세 disclosure에 둔다.
- 카드 제목15px, 본문·보조·상태13px 이상을 사용한다. 카드 상태는 Pod 준비와 서비스 실행 권한을 별도 배지로 유지한다.
- 선택 상세는 입력→현장 처리→서버 추론을 세로로 연결한다. 모바일 카드 선택은 상세 제목에 초점과 스크롤을 이동하며 갱신 중 disclosure 상태를 유지한다.


### 서비스 목록에서 개별 배치로 이동

- 등록 서비스 목록을 기본 진입으로 둔다. 서비스명·실행 상태, 입력/모델, 실행 위치를 한 행으로 비교한다.
- 목록 행: desktop 4열, 간격 24px, 제목 16px, 보조 13px. 700px 이하에서는 한 열로 전환한다.
- 선택 상세 상단: 목록 복귀 + 44px 서비스 선택 상자. 지도·입력 수집기·배치 이력은 선택한 계약으로 한정한다.
- 전체 워크로드/움직임 예시는 목록 하단 보조 동작으로 둔다. 기존 토큰·상태색을 재사용한다.


### 전체 장비 지도

- 서비스 목록과 같은 높이의 탐색 탭으로 노출한다. 전체 노드 기본 표시, 서비스·수집기 필터 기본값.
- 엣지 영역은 desktop 3열, 서버 1열. 1300px 이하 엣지 2열, 700px 이하 단일열. 카드 높이는 내용에 맞춘다.
- 물리 입력은 노드 내부 청록 2px 선으로 별도 표시하고 서비스 링크는 최소44px 터치 영역을 둔다.
- 선택 전에는 지도 전체 폭을 사용하고 실행체 선택 상세는 지도 아래에 표시한다.


### 오프로딩 연결 그래프

- 물리 입력/엣지/서버 3열, 1120px 내부 캔버스, 노드 240px, 세로 피치280px, 최대 카드 높이250px.
- 실제 HTML 버튼과 SVG 방향선을 결합한다. 바깥 화면 overflow 없이 내부 스크롤(최대680px, 모바일560px), 50–150% 확대·축소.
- 설정은 중립 점선, 원격 관측은 accent 실선, 로컬 복귀는 warn 점선이며 텍스트 상태를 함께 표시한다.
- 현재 노드와 워크로드의 개별 클릭은 기존 상세로 연결한다. 기본 그래프, 선택적으로 장비 카드 표현을 제공한다.


### 현재 실행 관측과 결과 피드백

- 그래프 상단에 실행 관측 패널: padding20px(모바일16px), 서비스 선택 최소56px, 실행체/준비/처리 상태 분리.
- 결과 시각·추론 경로·성능 3열, 모바일1열. 이력은 접힌 details로 제공한다.
- 새 결과는 노드와 원격 방향선을 1초×2회만 강조한다. 같은 결과의 재렌더는 음수 animation-delay로 남은 구간만 유지한다.
- 강조 끄기는 조회를 중지하지 않는다. reduced-motion은 이동 없이 상태·이력을 유지한다.


### 서비스별 구성도 (2026-09-09)

- 사용자 방향 전환에 따라 `/#architecture`는 서비스별 구성도다. 전체 플랫폼 영역 탐색을 대체하고 서비스 선택 → 입력 장비 → 처리 단계 → 설정된 실행 대상 → 결과의 관계를 표시한다.
- 기존 NEXUS 색·Pretendard·버튼을 재사용한다. 서비스 선택 칩 최소44px, 서비스 제목24px, 처리 카드16px 제목, desktop 다열 연결·700px 이하 세로 연결이다. 카드 간20px, 모바일24px, 캔버스 padding24px/모바일16px다.
- 구성도와 상세는 minmax(0,1fr):280px, 1250px 이하 상세를 아래로 배치한다. 단계·화살표·입력 장비를 native button으로 선택하며 모바일·태블릿 선택은 상세 제목으로 focus/scroll을 이동한다.
- 서비스별 graph.stages/depends_on/executions/targets 및 design_contract.inputs를 재사용한다. 단계 순서는 의존 관계로 정렬하고 순환·누락·중복 계약을 거부한다. 다른 서비스의 단계·실행 대상은 섞지 않는다.
- 입력 매핑은 EdgeX Device/resource와 물리 source ID를 구분한다. 고정 센서 데모의 local_recent 입력과 중앙 EdgeX 원시 데이터 저장·서비스 자체 결과 저장 경계를 유지한다.
- 서버 추론 대상은 별도 점선 카드와 ‘설정 경로’로 표시한다. 현재 경로 활성·가동·추론 성공·실행 권한을 추정하지 않는다. 실제 운영 보기는 service ID를 유지해 기존 서비스 상세로 이동한다.
- /state/services와 /state/service-resource-profiles를 진입·수동 새로고침 때 조회한다. 실패하면 생성된 /static/nexus/service-architecture.json을 ‘Git 계약 미리보기’로 명시 표시한다. 두 소스 모두 실패하면 오류와 재시도, 정상 빈 목록이면 빈 상태를 표시한다. 이 단계의 수동 조회 정책은 아래 서비스별 선택과 현재 실행 위치 절의 15초 자동 GET 갱신으로 대체되었다. 제어 요청은 없다.
- 정적 계약 파일은 scripts/build-service-architecture.py로 생성한다. service_catalog.json과 고정 데모 workload의 선언된 physical source만 사용하며 endpoint·자격증명·제어 계약은 export하지 않는다. 카탈로그 변경 후 재생성하고 test_nexus_architecture.js의 계약 일치 검증을 실행한다.
- 현재 정적 카탈로그의 서비스는 테스트베드 고정 센서 기준선 1개다. 옥동 실공장 서비스의 완료로 표시하지 않는다. 검증용 다중 서비스 데이터는 브라우저 모의 응답에만 존재한다.
- 검증 이미지는 /tmp에서 확인 후 삭제하며 output에 축적하지 않는다.

- 서비스 구성도 실행 위치(2026-09-10): namespace/workload가 일치하는 Running profile을 노드별로 묶는다. 실행체·담당 단계·노드별 Pod 수를 표시하고 Pod 이름·설정 노드·관측 시각은 disclosure로 펼친다. 노드 카드 최소320px/모바일100%, padding16px, 카드 간16px다.
- 설정 위치와 관측 위치를 분리한다. 원 profile 시각과 응답 시각에90초 freshness를 적용하고 미래5초 초과 시각도 거부한다. 조회 실패·오래된 관측·Running 미관측을 구분하며 설정 노드를 실제 위치의 fallback으로 사용하지 않는다. Pod Running을 AI 처리 성공으로 표시하지 않는다.
- 로컬 preview8784는 8772의 /state/services, /state/service-resource-profiles 두 GET만 전달한다. 다른 API·제어 요청은 전달하지 않는다. 노드·Pod 관측 성공을 서비스 처리 권한 활성으로 해석하지 않는다.

### 서비스 구성도 장비 이미지 (2026-09-10)

- 장비 유형별 투명 PNG 3종(Jetson, Raspberry Pi, 서버)을 노드 컨테이너 상단에 둔다. 그림180×170px, 상단 영역200px, 카드 반경10px, 노드 간64px로 위 실행 위치 카드 간격을 대체한다. 기존 NEXUS 토큰을 재사용한다.
- 알려진 노드 ID만 이미지에 매핑한다. 미등록 노드는 일반 노드 아이콘을 사용한다. 장비 이미지는 유형별 예시이며 실제 장비 사진·사양으로 해석하지 않는다.
- 서비스와 Pod는 이미지에 합성하지 않고 native button 및 disclosure로 표시한다. 서비스 계약의 단계 의존 관계를 관측된 노드에 투영하여 서로 다른 노드 사이에 정적인 점선 화살표를 그린다. 연결 버튼은 원본 단계 상세를 연다. 실제 트래픽이나 활성 추론 경로로 표시하지 않는다.
- resize와 Pod disclosure 변경 시 연결선을 재계산한다. 모바일은 세로 장비 배치와 수직 화살표이며 카드 선택 후 상세 제목으로 focus/scroll한다. 오래되거나 실패한 관측에서는 장비 위치·화살표를 표시하지 않는다.
- 최종 자산과 생성 프롬프트는 app/static/nexus/assets/hardware에 보관한다. QA 스크린샷은 /tmp에서 검토 후 삭제한다.

### 단일 서비스 구성 화면 (2026-09-10, 사용자 후속 확정)

- 위의 장비 지도와 별도 단계 구성도 2영역을 단일 캔버스로 합친다. 입력 장비 → 관측 실행 노드 → 노드 안 실행체·담당 단계만 표시한다. 중복 단계 파이프라인과 상시 상세 패널은 제거한다. 등록 서비스가 1개면 중복 선택 칩을 생략한다.
- 데스크톱은 입력156px + 간격48px + 노드 자동 열(최소280px)이다. 장비 이미지112px, 장비 헤더120px로 줄인다. 1000px 이하 입력을 상단으로 옮기고 700px 이하 노드를 세로로 배치한다.
- 단계·입력 매핑·연결 선택은 native modal dialog로 상세를 연다. Pod 이름·관측 시각도 상세 안에서 펼친다. Escape 및 닫기 버튼으로 닫으며 원래 버튼으로 초점을 돌린다. 모바일에서도 긴 페이지 아래로 이동시키지 않는다.
- 장비 이미지는 built-in imagegen 유형 예시 3종을 재사용하며 새로운 이미지나 output QA 파일은 추가하지 않는다. 입력 연결은 source 단계의 실제 관측 노드가 확인될 때만 그린다.

### 대시보드형 서비스 토폴로지 (2026-09-10, 후속 시각 보정)

- 중복 페이지 제목·툴바를 서비스 제목과 운영 상세/새로고침 한 줄로 합친다. 관측 노드·관측 실행체/계약 실행체·처리 단계·조회 시 처리 권한을 단일 요약 행으로 표시한다. 실행 권한을 Pod 수로 추론하지 않는다.
- 단일 점 격자 캔버스에서 입력160px, 노드320px, 노드 간112px를 사용한다. 48px 장비 그림은 노드 헤더 보조로 두고 실행체와 단계 버튼이 중심이다. 수집/일반/서버 실행체 좌측 선은 physical/accent/virtual 토큰을 재사용한다.
- 실제 namespace/workload 관측으로 만든 단계 포트를 계약 의존 관계에 따라 연결한다. 내부 단계 연결은 얇은 선, 노드 간 연결은 점선 곡선이며 입력·추론 입력·판정 결과 라벨은 직접 클릭할 수 있다. 노드 아래의 중복 연결 목록은 제거한다. 실제 트래픽 애니메이션은 없다.
- 확대/축소는35–150%, 화면 맞춤은 가용 폭을 기준으로 계산한다. 노드와 포트의 좌표를 배율로 보정하여 연결선을 재계산한다. 작은 화면에서는 페이지 가로 넘침 없이 지도 영역만 가로 스크롤하고, 화면 맞춤으로 전체 구조를 볼 수 있다.
- 상세는 기존 native dialog를 유지한다. 정적 계약·관측 누락·실패 경계도 유지한다. 기존 중복 CSS는 제거했다. QA 이미지는 /tmp 검토 후 삭제하며 output에 축적하지 않는다.

### 서비스별 선택과 현재 실행 위치 (2026-09-10)

- 사용자가 서비스별 현재 실행 위치 적용을 요청했다. 기존 수동 갱신 전용 정책을 15초 자동 GET 갱신으로 대체한다. 구성도 화면이 활성이고 문서가 보일 때만 조회하며, 자동 갱신 일시정지와 수동 새로고침을 제공한다. 요청 중복은 막고 기존 5초 timeout을 유지한다.
- 상단 native select에서 `/state/services`의 등록 서비스와 `/state/service-resource-profiles`의 namespace/workload를 별도 optgroup으로 선택한다. 선택 ID를 URL의 service query에 보존한다. 등록 서비스의 계약 연결과 계약 미등록 실행 워크로드를 같은 AI 서비스로 취급하지 않는다.
- 워크로드 보기는 정확한 namespace/name 관측 노드와 Pod만 표시한다. 입력 장비·단계 의존 관계를 만들지 않고, replica가 여러 노드에 있으면 각 노드에 표시한다. 선택한 워크로드가 새 관측에서 사라져도 선택을 유지하고 Running 미관측으로 전환한다.
- 현재 Pod 실행 위치와 서비스 처리 상태를 별도 행으로 제공한다. 서비스 상태는 API 응답·처리 결과·실행 권한 관측의 freshness를 확인한다. STANDBY/lease 만료는 처리 대기로 표시하며 Pod Running에서 AI 처리 성공을 추정하지 않는다. 등록 계약 노드와 실제 노드가 다르면 실행체 카드에 표시한다.
- 자동 갱신은 지도와 상태 영역을 갱신하고 선택, 지도 배율·스크롤, 열린 상세 및 Pod disclosure를 보존한다. 상세는 연 시점의 기준 시각을 명시한다. 일반 워크로드에는 AI 처리 상태 미연동을 표시한다.
- 기존 NEXUS 토폴로지·장비 이미지·native dialog를 재사용하며 backend catalog/실행 제어는 변경하지 않는다.


### 구성도 최근 처리 결과 (2026-09-10)

- 실행 위치 요약 아래에 서비스 자체 저장 결과를 표시한다. 판정, 통합 이상 점수, 진동 RMS·온도 raw 평균, 추론 경로·처리 시간의 4열이며 1050px 이하 2열이다. 기존 surface/line/accent와 24px 패딩(모바일16px)을 재사용한다.
- 선택 서비스의 명시적 observability 계약만 GET 조회한다. 현재 지원은 sensor-anomaly-v1이며 연결 계약이 없는 워크로드는 미연동으로 표시한다. 자동 갱신은 기존15초 주기를 따르고 결과 시각과 조회 시각은 별도로 표시한다.
- 이전 최신 결과보다 새로운 observed_at을 가진 결과만 새 수신으로 센다. 초기 조회·중복·과거 결과 추가를 새 처리로 표시하지 않는다. 새 수신 수는 조회된 최대12건 범위이며 처리량 전체가 아니다.
- 실패 시 마지막 저장값을 보존하되 조회 실패와 과거 값임을 명시한다. 응답·결과90초 freshness와 미래5초 허용범위를 적용한다. Pod Running, 정상 판정과 현재 연속 처리 여부를 합치지 않는다.
- 결과 이력은 native details/table이며 자동 갱신 중 펼침 상태를 보존한다. 원시 온도값을 섭씨로 바꾸거나 없는 지연값을0으로 표시하지 않는다.


### AI 실행 지도와 부하 제어 (2026-09-11)

- NEXUS의 현재 토큰으로 하나의 실행 workspace를 구성한다. 요청 입구 → 실제 실행 노드
  분기 지도를 왼쪽, 부하·진행·중단·승인을 오른쪽에 둔다. 850px 이하는 세로로 쌓는다.
- 패널 padding16px, 지도 padding16px, 1.6:1 두 열과 gap20px, 노드 최소120px/간격12px다.
  하단 지표는 desktop6열/1180px 이하3열/500px 이하2열이다. 클릭 영역 최소44px.
- 현재 경로는 강조색 실선, 추천은 주의색 점선, 준비는 강조색 점선과 글자로 구분한다.
  실제 요청이 관측될 때만 선을 움직인다. idle은 `요청 대기 중`이며 spinner가 없다.
- 실행 접수·부하·모델 준비에는 spinner, 부하에는 경과시간과 실제 건수 및 불확정 진행
  막대를 쓴다. 가짜 완료 백분율은 없다. 모션 줄이기 및 stale 상태에서 이동을 끈다.
- 노드 선택과 focus는 polling 후 유지한다. 긴 진단과 과거 실행 응답은 disclosure다.


- AI 부하 제어 후속: 시작/제거 버튼을 나란히 고정 표시하고 단일 시험 요청은 위 보조
  버튼으로 둔다. 제거는 실행 중에만 활성이고 접수·진행·완료를 표기한다. 지도 노드에
  CPU·메모리·GPU 3열 수치와 meter, 노드 수집시각을 넣는다. 미수집은 값/막대 없음이다.
