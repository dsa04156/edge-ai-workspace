# 운영 현황 디자인

사용자 제공 메인 참조 이미지 기반의 한국어 운영 화면. `overview-screen`에만 적용한다.

- 프레임: sidebar 200px / header 64px / content padding 20px 22px.
- 색: canvas #f2f6fb / rail #102131 / cards #fff / border #dfe8f3.
- 강조: blue #1479ed / ready #0bbf91 / warning #f6ad24 / unknown #91a1b7.
- 글꼴: 기존 Pretendard, page title 29px, card title 15px, KPI 34px, table 12px.
- 레이아웃: KPI 4열 → 자원 비교·노드 준비 상태·서비스 p95 3열 → 점검/이력과 서비스/물리 장비 1.6:1.
- 1250px 이하 차트 재배치, 900px 이하 2열 KPI 및 단일 카드, 600px 이하 가로 탐색 메뉴.
- Chart.js 4.5.1과 Bootstrap Icons 1.13.1은 vendor에서 제공하며 외부 CDN 런타임 의존 없음.
- API 실패와 60초 이상 지난 자원 사용률은 미관측. p95는 현재 원천·양수 표본 수·valid 성능 측정이 모두 필요.
- 기간 추이는 제공 API가 없어 표시하지 않음. 현재 노드별 실측 비교로 표현.
