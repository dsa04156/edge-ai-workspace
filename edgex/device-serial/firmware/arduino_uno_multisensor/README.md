# Arduino Uno 다중센서 운영 펌웨어

이 디렉터리는 `etri-dev0001-jetorn`에 USB로 연결된 Arduino Uno R3
(`2341:0043`, serial `75035303230351E0D171`)의 운영 스케치와 application 롤백
이미지를 보관한다. 물리 source ID와 wire contract는 `arduino-001`로 유지하며 EdgeX
Device 여섯 개의 read-only resource로 fan-out한다.

## 핀과 전송 계약

| 값 | Uno pin | JSON field |
|---|---|---|
| 조도 | `A0` | `sensor=light`, `value` |
| 온도 raw | `A1` | `sensor=temperature`, `raw` |
| 자기센서 | `D4` | `sensor=magnetic`, `value` |
| 가속도 X | `A2` | `sensor=acceleration`, `x` |
| 가속도 Y | `A3` | `sensor=acceleration`, `y` |
| 가속도 Z | `A4` | `sensor=acceleration`, `z` |

전송 설정은 115200 bps, 8N1이다. 한 sample cycle마다 위 네 JSON line을 전송한다.
현재 cycle delay는 100 ms이며 기존 1,000 ms보다 짧게 유지해 재연결 뒤 다음 유효 frame이
400 ms gate 안에 들어오도록 한다.

## 원본 확인과 롤백

2026-09-01 Jetson의
`/home/etri/Arduino/sketch_may20a/sketch_may20a.ino`를 읽어 확인했다.

- 원본 source SHA-256:
  `49eda328bb58b76f66f93ba28f8a7eca2c0f50adce94fa405cf2ea1d3a29b234`
- Uno flash readback의 활성 프로그램 앞 2,614 bytes와 동일 host toolchain으로 다시 빌드한
  원본 application이 byte-for-byte 일치했다.
- 롤백 application:
  `backup/arduino-uno-75035303230351E0D171-original-application-20260901.hex`
- 롤백 application SHA-256:
  `95728fbdbf78e472d503b4b85599522f402922de5985b3c8eca0a7ba4e736f4c`

이번 변경은 application flash만 갱신했다. bootloader, fuse와 EEPROM은 쓰지 않았다.
롤백 시 Device Service를 먼저 0 replica로 내린 뒤 exact by-id port에 다음처럼 원본
application만 기록하고 verify한다.

```bash
avrdude -C /etc/avrdude.conf \
  -p atmega328p -c arduino \
  -P /dev/serial/by-id/usb-Arduino__www.arduino.cc__0043_75035303230351E0D171-if00 \
  -b 115200 -D \
  -U flash:w:backup/arduino-uno-75035303230351E0D171-original-application-20260901.hex:i
```

400 ms 복구는 펌웨어 cadence만으로 보장되지 않는다. Device Service가 Linux termios의
`HUPCL`을 해제해 포트 종료·재연결 때 DTR 하강으로 Uno가 자동 재부팅되지 않도록 해야 한다.
