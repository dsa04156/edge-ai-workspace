# ESP32 MPU6050 USB Serial 예제

Raspberry Pi에 USB로 연결한 ESP32가 MPU6050 6축 값을 `device-serial`의
`mpu6050-imu-v1` parser 계약으로 전송하는 운영 예제다. 외부 MPU6050 라이브러리는
사용하지 않고 Arduino `Wire` API로 필요한 register만 읽는다.

## 연결 계약

- Serial: `115200 8N1`
- 물리 source ID: `mpu6050-001`
- MPU6050 주소: `0x68` 또는 `0x69`
- ESP32 SDA/SCL: GPIO 21/22
- 가속도 단위: `m/s2`
- 각속도 단위: `rad/s`
- 출력: 한 줄에 JSON 객체 하나

2026-07-28 dev0003 실장비는 CH340 USB bridge를 사용하는
`ESP32-D0WD-V3 revision 3.1`로 식별했다. host stable path는
`/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`이다.

## 배선

| ESP32 | MPU6050/GY-521 |
|---|---|
| `3V3` | `VCC` |
| `GND` | `GND` |
| `GPIO21` | `SDA` |
| `GPIO22` | `SCL` |
| `GND` | `AD0` (`0x68` 사용 시) |

`AD0`를 3V3에 연결하면 주소는 `0x69`가 된다. ESP32의 3.3V 논리 기준을 사용한다.

## 빌드와 업로드

Arduino CLI에 Espressif 공식 package index와 `esp32:esp32` core가 설치된 상태에서
sketch 디렉터리에서 실행한다.

```bash
arduino-cli compile --fqbn esp32:esp32:esp32 .
arduino-cli upload \
  --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --fqbn esp32:esp32:esp32 .
```

업로드 전 동일 포트를 연 Device Service Runtime이 없어야 한다. Controller 승인 Saga가
실행 중이면 먼저 종료 또는 rollback된 것을 확인한다.

## 출력 판정

센서가 ACK하지 않으면 펌웨어는 1초마다 다시 탐색하며 다음 상태 JSON을 출력한다.

```json
{"type":"status","device_id":"mpu6050-001","status":"sensor_not_found","who_am_i_0x68":null,"who_am_i_0x69":null}
```

이 상태 메시지는 배선 진단용이며 EdgeX telemetry Event가 아니다. 센서가 확인되면 별도
재부팅 없이 다음 6축 JSON-line으로 전환한다.

```json
{"device_id":"mpu6050-001","sensor":"imu","acceleration_x":0.012000,"acceleration_y":-0.021000,"acceleration_z":9.801000,"gyro_x":0.001000,"gyro_y":-0.002000,"gyro_z":0.003000}
```

운전 중 I2C read가 실패해도 sensor 상태를 해제하고 다시 탐색하므로 분리·재연결 뒤
자동 복구한다. 이 6축 출력이 실제로 시작되기 전에는 Device Service가 Ready여도
EdgeX 첫 Event 확인은 완료되지 않는다.

## dev0003 현재 확인 결과

2026-07-28에 ESP32 compile, flash hash 검증, USB Serial 상태 JSON 출력까지 확인했다.
다만 ESP32의 여러 일반 I2C pin pair와 Raspberry Pi bus 1에서 `0x68`, `0x69` 모두 ACK가
없었다. 따라서 현재 남은 조건은 위 네 전원·I2C 선의 실물 연결 확인이다. 배선 뒤 정상
6축 JSON을 확인하고 실패 candidate를 재시도해야 한다.
