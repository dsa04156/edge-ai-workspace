# Jetson 호스트 DNS 수정·검증

2026-09-07 사용자 승인 후 `etri-dev0001-jetorn` 호스트에 적용했다.
서비스 이름으로 실제 추론이 성공했다. 장비 재부팅 후 검증은 **미검증**이다.

## 원인과 적용

기존 Pod는 EdgeMesh DNS `169.254.96.16`으로 서비스 이름을 정상 해석했다.
호스트는 systemd-resolved stub `127.0.0.53`과 유선 DNS `10.254.16.61/62`를
사용하며 클러스터 도메인 경로가 없었다. 정확한 서비스 FQDN 조회는
`No appropriate name servers or networks for name found`로 실패했다.
EdgeMesh 전체 장애나 Jetson 추론 장애는 아니었다.

`edgemesh0`에 per-link DNS를 직접 지정하는 시험은 `NO-CARRIER`, DNS scope 없음
상태에서 조회에 실패해 `resolvectl revert edgemesh0`로 되돌렸다.
최종 적용은 다음 두 설정이다.

- `/etc/systemd/resolved.conf.d/90-edgemesh-host-dns.conf` 신규 파일:

  ```ini
  [Resolve]
  DNS=169.254.96.16
  Domains=~cluster.local
  ```

- NetworkManager `Wired connection 1`의 기존 `ipv4.dns-search`에 `~.` 추가.
  더 구체적인 `cluster.local`은 EdgeMesh로, 나머지는 기존 유선 DNS로 보낸다.
  기존 IP·DNS 서버·기본 경로는 변경하지 않았다.

NetworkManager에 DNS 설정을 reapply하고 systemd-resolved만 재시작했다.
EdgeCore, EdgeMesh, 센서 Pod는 재시작하지 않았다. 기존 DNS 상태와 search 설정은
Jetson의 `/var/backups/vd-host-dns.6KOp53/`에 보관했다.
이 설정은 현재 유선 연결 기준이다. 다른 기본 네트워크로 전환하면 DNS 경로를 재검증한다.

## 검증 결과

- 호스트 `resolvectl`과 Python socket: 시험 Service FQDN → `10.103.255.142` 성공.
- `kubernetes.default.svc.cluster.local` → `10.96.0.1` 성공.
- `example.com` → 기존 유선 인터페이스 `enP8p1s0` DNS로 성공.
- Jetson에서 `http://vd-demo-001.virtual-device-test.svc.cluster.local:8080`으로 실제 요청.
  요청 ID `jetson-dns-fixed-20260907`, 결과 `setosa`, 성공 건수 0→1, statusMatched=true.
- aggregator lastSuccess와 실제 응답 완전 일치, 연결 request_observed 확인.
- inFlight=0 확인 후 시험 Deployment를 replicas=0으로 복원하고 Pod 삭제 확인.
- 영속 설정 저장 및 resolved 재시작 후 조회 성공. 장비 재부팅은 수행하지 않았다.

실측 JSON·DNS 출력은 `output/vd-host-dns/`에 있다.

## 확인·복구 명령

아래는 Jetson 터미널에서 실행한다. 호스트에 rtk가 없으면 원래 명령을 사용한다.

```bash
resolvectl query vd-demo-001.virtual-device-test.svc.cluster.local
resolvectl query example.com
cat /etc/systemd/resolved.conf.d/90-edgemesh-host-dns.conf
nmcli -g ipv4.dns-search connection show 'Wired connection 1'
```

설정을 되돌릴 때는 기존 search 설정을 복원하고 이번 drop-in만 제거한다.
이후 같은 설정에 다른 변경이 있으면 먼저 차이를 검토한다.

```bash
sudo bash <<'SH'
set -e
old_search=$(cat /var/backups/vd-host-dns.6KOp53/ipv4-dns-search.before)
nmcli connection modify 'Wired connection 1' ipv4.dns-search "$old_search"
nmcli device reapply enP8p1s0
rm /etc/systemd/resolved.conf.d/90-edgemesh-host-dns.conf
systemctl restart systemd-resolved
SH
```

라우팅 도메인은 가장 구체적인 일치 항목으로 DNS를 선택한다.
[systemd 공식 DNS 라우팅 설명](https://github.com/systemd/systemd/blob/main/docs/RESOLVED-VPNS.md)을 따른다.
