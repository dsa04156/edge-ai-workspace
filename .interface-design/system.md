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
| Canvas | `#f2f5f7` | 전체 배경 |
| Rail | `#e9eef1` | canvas보다 한 단계 짙은 밝은 회색 |
| Surface | `rgba(255, 255, 255, .84)` | 기본 반투명 panel |
| Raised surface | `rgba(248, 250, 252, .96)` | popover·상세 표면 |
| Control | `rgba(15, 35, 48, .055)` | inset control·inactive state |
| Standard line | `rgba(15, 35, 48, .12)` | 조용한 구조 분리 |
| Primary text | `#172632` | 핵심 상태·수치 |
| Secondary text | `#526573` | 설명·label |
| Tertiary text | `#748590` | metadata·timestamp |
| Interaction accent | `#087f8c` | 선택·focus·주 동작만 |
| Healthy | `#168253` | 정상 상태만 |
| Warning | `#986400` | 주의 상태만 |
| Error | `#c13f4c` | 장애 상태만 |
| Information | `#286fae` | 링크·정보 상태만 |

- 색상 비율은 중립 60%, 보조 표면 30%, accent와 상태색 10% 이하로 유지한다.
- status 색상은 텍스트·아이콘·배지 상태와 함께 사용하며 색상만으로 의미를 전달하지 않는다.

## 깊이와 표면

- 전략: 세 단계의 반투명 surface + 낮은 투명 shadow. 여러 depth 전략을 섞지 않는다.
- Canvas → panel → raised detail 순으로 백색도와 불투명도를 소폭 높인다.
- 기본 panel: `18px` radius, `1px` 저대비 line, `0 16px 40px rgba(36,58,72,.10)` shadow.
- control: 주변보다 소폭 짙은 inset fill, `10px` radius.
- mobile panel: `16px` radius.
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
- desktop workspace padding: `24px 26px 40px`.
- mobile workspace padding: `18px 16px 32px`.
- control hit area: 기본 `44px`, mobile 탭은 최소 `40px`.
- 관련 정보는 조밀하게 묶고 section 사이에는 24px 이상의 명확한 호흡을 둔다.

## 레이아웃 패턴

- Desktop: `232px` 운영 레일 + command bar + workspace. 보조 inspector는
  `300–340px`이고 main content에 종속된다.
- `1180px` 이하: 운영 레일을 sticky 가로 스크롤 탭으로 전환한다.
- `760px` 이하: 단일열 workspace, compact header, 가로 스크롤 탭을 사용한다.
- 페이지 전체의 가로 overflow는 허용하지 않는다. 넓은 table/graph만 내부 scroller를 쓴다.

## 재사용 컴포넌트

### 운영 레일 탭

- Desktop `44px` 높이, `11px` radius, `13px/590`.
- inactive는 투명, hover는 control fill.
- active는 `rgba(90,200,200,.14)` fill과 `3px` 청록 indicator를 함께 사용한다.
- Mobile은 `40px` 높이의 가로 탭이며 indicator를 아래쪽 `2px` line으로 전환한다.

### 상단 command bar

- `76px` 최소 높이, `14px 24px` padding, blur `22px`.
- 검색은 밝은 inset control이다. 새로고침은 청록 soft fill을 사용하는 보조 주 동작이다.
- Mobile은 제목·새로고침 한 행, 검색 한 행으로 쌓는다.

### 운영 분류 요약

- 세 개의 독립 카드 대신 하나의 `18px` segmented surface를 사용한다.
- Desktop은 3열, segment 사이에 저대비 divider를 둔다.
- Mobile은 세로 3행으로 바꾸고 label/caption 왼쪽, value 오른쪽에 둔다.

### Panel

- `18px` radius, `1px` low-opacity border, translucent surface, shallow shadow.
- nested content는 더 밝은 동일 계열 surface 또는 divider로만 구분한다.
- 경고 panel은 panel 전체를 상태색으로 채우지 않고 indicator·label에만 상태색을 쓴다.

### 물리 source → 관측 트윈 → 서비스 row

- 연결된 row의 시작점에 `2px` 청록 rail을 사용한다.
- inventory 상단에는 연결 흐름을 암시하는 얇은 청록 line을 둘 수 있다.
- service binding은 N:M을 지원하며 상태, 연결 여부, freshness를 하나의 값으로 합치지 않는다.

### Button과 form control

- 기본 높이 `44px`, control radius `10–11px`.
- hover는 색과 표면만 미세하게 변하고, active는 `scale(.97)`을 사용한다.
- focus는 `0 0 0 3px rgba(90,200,200,.34)`.
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
- 기존 native DOM·데이터 권위·상태 판단 계약은 시각 개선 때문에 바꾸지 않는다.
- 새 색상·radius·spacing을 임의로 추가하지 않고 위 토큰과 4px grid를 먼저 재사용한다.
- 반복 컴포넌트의 측정값이 바뀌면 구현과 이 파일을 함께 갱신한다.
- 최종 화면은 desktop과 390px mobile에서 직접 확인한다.
