# 혼합 디바이스 관리 재검증

2026-09-15 사용자 재검증 요청에 따라 실행했다. [요약 JSON](recheck-summary.json),
[100개·실제 병렬 프로세스 결과](verification.json), [브라우저 쓰기 후 API 저장값](ui-api-readback.json).

- runtime-operator152개, 관련 aggregator Python99개, 수정 후 JavaScript314개 통과.
- 모의 EdgeX1+영속 가상99개 관리 재시험 통과: 개별 조회·제어·이력·재시작 보존·장애 구분.
- 실제 기존 추론 프로세스4개/44요청 성공 재확인. 실제 Kubernetes Pod 시험과 구분한다.
- 격리한 loopback API/SQLite를 브라우저에 연결해 프로파일 생성→3개 등록→2번 객체 이름/연결
  변경→정지→이력 조회를 수행했다. API readback revision3과 다른2개 revision1 유지, 실행체 할당0 확인.
- 발견한 오류1건: Chrome이 ID 접두어의 HTML pattern을 Unicode Sets 정규식으로 해석할 때
  문자 클래스의 하이픈 문법이 잘못되어 브라우저 검증이 비활성화됐다. 명시적 하이픈 대안으로 수정하고
  잘못된 ID 차단/정상 ID 등록을 실제 브라우저와 회귀 시험에서 확인했다. 정적 파일 URL도 갱신했다.
- 격리 UI의 기타 서비스 목록은 운영 서버의 기존 미배포 API를 GET으로 읽으므로404가 있었다.
  새 managed 등록·수정·제어 API의 실패가 아니며 운영 쓰기는 전달하지 않았다.
- 운영 read-only: 기존 operator1/1 Ready, 새 `/api/managed-devices`는404로 미배포 확인.
  로컬 Docker socket 접근 거부로 실제 Pod 병렬 시험은 수행하지 않았다.

운영 배포·장비 제어 변경 없음. 공식100개 목표 달성 판정은 기존 인수 조건을 유지한다.
