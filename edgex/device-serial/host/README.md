# USB Serial 동적 endpoint

Kubernetes가 `/dev/serial/by-id/*` 문자 장치 하나를 직접 bind mount하면 Pod가 만들어진
시점의 major/minor가 고정된다. USB 재열거 후 `ttyACM1`이 `ttyACM0`으로 바뀌면 호스트의
`by-id` symlink는 갱신되지만 실행 중인 컨테이너는 철거된 옛 장치를 계속 본다.

이 디렉터리의 호스트 규칙은 USB serial identity를 확인한 뒤 다음 고정 endpoint의
문자 장치 노드를 원자적으로 교체한다.

```text
/run/edgeai/devices/arduino-001
```

Device Service에는 위 디렉터리 하나만 read-only로 mount하고 EdgeX `Port`는
`/dev/edgeai/arduino-001`로 설정한다. 전체 호스트 `/dev` 또는 `/sys`를 Device Service에
mount하지 않는다.

## 설치

Jetson 호스트에서 다음 세 파일을 설치한다.

```bash
sudo install -m 0755 edgeai-device-node /usr/local/sbin/edgeai-device-node
sudo install -m 0644 90-edgeai-serial-endpoints.rules /etc/udev/rules.d/90-edgeai-serial-endpoints.rules
sudo install -m 0644 edgeai-serial-endpoints.conf /etc/tmpfiles.d/edgeai-serial-endpoints.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/edgeai-serial-endpoints.conf
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=tty
sudo udevadm settle
```

확인은 다음 두 값의 major/minor가 같은지 비교한다.

```bash
stat -Lc '%t:%T %n' /dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_75035303230351E0D171-if00
stat -Lc '%t:%T %n' /run/edgeai/devices/arduino-001
```

## 다른 USB Serial 장비 추가

공통 helper는 그대로 두고 udev rule에 승인된 장비 한 줄만 추가한다. 최소 식별자는
`ID_VENDOR_ID`, `ID_MODEL_ID`, `ID_SERIAL_SHORT`이며 논리 이름은 소문자·숫자·하이픈만
사용한다. 장비 firmware의 재연결 동작은 별도 `RecoveryStrategy` 계약으로 선택한다.
임의 command 문자열을 catalog나 사용자 입력으로 받지 않는다.

제거 이벤트가 늦게 도착해도 helper는 현재 endpoint의 major/minor가 제거 대상과 같을
때만 삭제한다. 새 장치 노드를 옛 제거 이벤트가 지우지 않는다.
