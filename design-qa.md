# 운영 현황 메인 디자인 QA

- source visual truth: `/home/jinuk/6a8c9272-a22a-46eb-8261-b6742bbe3fd2.png`
- implementation: `http://127.0.0.1:8772/#overview`
- implementation screenshot: `/home/jinuk/codex-work/jinuk/output/playwright/overview-desktop-final.png`
- mobile screenshot: `/home/jinuk/codex-work/jinuk/output/playwright/overview-mobile.png`
- viewport: desktop 1536 × 1024 CSS px; mobile 390 × 844 CSS px
- source / desktop screenshot: both 1536 × 1024 pixels, screenshot scale CSS, 1:1 normalization. Mobile is a full-page capture.
- state: 실제 관측, CPU 선택. 참고 이미지의 서비스 12개 등은 예시이며 구현은 실제 등록 서비스 1개, 노드 7개, EdgeX Device 13개, 물리 source 2개, 서비스 점검 항목 3개를 표시한 상태에서 비교했다.

## 비교 근거와 이력

동일 tool input에서 원본과 구현 이미지를 함께 열어 전체 구도를 비교했다. 1536px 원본 크기에서 카드 제목·수치·표·버튼을 읽을 수 있어 별도 확대 crop은 필요하지 않았다.

1. v1 (`overview-desktop-v1.png`): P2. 별도 도구 행과 높은 차트·이력 행 때문에 하단 서비스 목록이 첫 화면 밖에 놓였다. 원본은 KPI y156, 구현은 y206이었다.
2. v2 (`overview-desktop-v2.png`): 상태·갱신·장비 지도 버튼을 넓은 화면의 헤더에 배치, 차트 높이와 이력 간격 축소. KPI가 y158로 올라왔다. P2. 점검 표의 높은 행 때문에 하단 장비 목록 끝이 잘렸다.
3. final (`overview-desktop-final.png`): 점검 표의 버튼 최소 높이와 셀 여백을 조절. 하단 서비스·장비 카드가 y987 안에 들어온다. 원본과 재비교해 actionable P0/P1/P2 없음.

## 필수 표면 검토

- Typography: 기존 Pretendard 한국어 글꼴을 유지. 제목 29px, 카드 제목 15px, 주요 수치 34px, 표 본문 12px. 한국어 실제 서비스명 줄바꿈과 원본 영어 문구의 차이는 의도된 현지화다.
- Layout: 200px 남색 내비게이션, 64px 헤더, KPI 4열, 차트 3열, 하단 1.6:1 표 구성. 원본 구성과 작은 간격을 유지했다. 소량의 실제 데이터에 예시 행을 추가하지 않았다.
- Colors: navy #102131, canvas #f2f6fb, white cards, border #dfe8f3, blue #1479ed, green #0bbf91, amber #f6ad24. 상태는 색뿐 아니라 문자로도 구분한다.
- Assets: 기존 NEXUS 브랜드·메뉴 아이콘 유지. 새 KPI/검색 아이콘은 Bootstrap Icons 1.13.1 원본 SVG 파일, 차트는 Chart.js 4.5.1 실제 데이터 렌더링. 두 라이선스를 vendor에 포함했다. 원본의 가상 로고를 새로 모사하지 않았다.
- Copy: 한국어 실제 운영 정보. 등록 Device와 물리 source, Kube Ready와 AI 처리, 현재 상태와 과거 이력을 구분한다. 지원되지 않는 과거 자원 추이 대신 현재 노드별 비교, 유효 표본이 없는 p95는 미측정 상태로 표시한다. 원본의 기간 선택은 실제/목표/구현 근거 전환으로 대체했다.

## 동작 및 상태 확인

- 검색: arduino 검색 → 실제 물리 장비 상세. 결과 없음 상태와 Escape 닫기 확인.
- GPU/CPU 지표 전환, 점검 KPI → 점검 표로 포커스 이동 확인.
- 서비스 행 → `?service=sensor-anomaly-demo#services`, 전체 장비 지도 → `?workloads=all#service-map` 확인.
- 1366, 1024, 768, 390px에서 document scrollWidth가 viewport와 같음. 작은 화면의 서비스 표만 내부 스크롤한다.
- 기존 JavaScript 테스트 전체 228개 통과. 추가 6개는 fan-out 수, stale/failed/미관측, 실제 0, Lease 만료, 유효 성능 표본과 이벤트 원 시각을 검증한다.
- 첫 연결에서 JS pageerror 0. 미리보기 프로세스가 SIGTERM 종료된 후 polling 연결 오류가 발생한 환경 문제를 확인하고 서버 재시작. 새 overview-verified 세션에서 다시 페이지 로드, 콘솔 오류/경고 0 확인. 종료 신호의 외부 원인은 확정하지 않았다.

## 남은 차이

- 현재 실제 서비스와 장비 수가 예시보다 적다. 빈 행이나 허구의 과거 그래프를 채우지 않는다.
- 다른 상세 화면은 기존 레이아웃을 유지한다. 이 작업의 대상은 메인 운영 현황이다.
- p95 현재 표본은 없으며 운영 처리 재개는 UI 작업의 범위가 아니다.

final result: passed
