# Edge AI Apple Operations Design System

## 목적

이 대시보드는 물리 디바이스, 엣지 노드, EdgeX 관측 상태와 AI 서비스 연결을 빠르게
판단하는 운영 화면이다. 장식적인 BI 카드보다 상태, 최신 관측, 연결 관계가 먼저 읽혀야
하며 운영자가 10초 안에 이상 대상과 영향을 받는 서비스를 찾을 수 있어야 한다.

## 시각 언어

- 색상은 주간 제어실의 밝은 회색 패널과 백색 계기판, 모니터 유리의 반투명 표면을
  기본으로 한다.
- 청록색은 현재 선택과 주요 동작에만 사용한다. 녹색·황색·적색은 각각 정상·주의·장애
  상태에만 사용하고 장식에는 사용하지 않는다.
- 한 화면에서 캔버스, 반투명 패널, 떠 있는 상세 표면의 세 깊이만 사용한다.
- 그림자는 얕게, 경계선은 반투명하게 사용해 패널을 분리한다. 장식용 gradient는 쓰지 않는다.

## 정보 위계와 타이포그래피

- 시스템 글꼴을 사용하며 큰 제목은 촘촘한 자간, 기술 수치는 tabular number로 표시한다.
- 페이지 제목보다 상태와 핵심 수치가 먼저 눈에 들어오게 한다.
- 설명은 한 단계 낮은 회색으로 두고 긴 식별자는 내용 영역 안에서 안전하게 줄바꿈한다.
- 4px를 기본 단위로 12/16/24/32px 간격을 반복한다.

## 핵심 컴포넌트

- 왼쪽 밝은 회색 운영 레일: 활성 화면은 채도가 낮은 청록 재질과 가는 표시선으로 구분한다.
- 상단바: 클러스터 문맥, 검색, 갱신을 얇은 반투명 재질에 배치한다.
- 운영 요약: 세 분류를 각각 떨어진 카드로 만들지 않고 하나의 segmented surface로 묶는다.
- 패널: 18px radius, 얕은 그림자, 반투명 표면으로 일관되게 구성한다.
- 연결 signature: `물리 source → 관측 트윈 → AI 서비스`를 가는 청록 status rail로 반복한다.
- 폼과 버튼: 최소 44px hit target, 명확한 focus ring, 누를 때 0.97 scale 피드백을 제공한다.

## 반응형과 접근성

- 1180px 아래에서는 왼쪽 레일을 가로 스크롤 가능한 탭으로 전환한다.
- 760px 아래에서는 요약을 하나의 세로 segmented surface로 바꾸고 패널을 한 열로 쌓는다.
- `prefers-reduced-motion`, `prefers-reduced-transparency`, `prefers-contrast`를 지원한다.
- 색상만으로 상태를 전달하지 않고 텍스트와 배지를 함께 유지한다.

## 최종 CSS 레이어

`apple-dashboard.css` is the final visual contract. 기존 기능별 CSS를 제거하지 않지만 마지막에
로드하여 토큰, app frame, navigation, surface, control, motion과 responsive 규칙을 한곳에서
통제한다. 기능별 DOM과 이벤트 계약은 바꾸지 않는다.

## 범위 경계

- 화면은 observed state, read-only explanation, 검증된 관리 흐름과 dry-run만 표시한다.
- 물리 디바이스 권위는 EdgeX, node/workload 권위는 KubeEdge/Kubernetes에 둔다.
- 가상 하드웨어, 완성된 자율 orchestration, runtime migration 또는 actuator 제어를 암시하지 않는다.
