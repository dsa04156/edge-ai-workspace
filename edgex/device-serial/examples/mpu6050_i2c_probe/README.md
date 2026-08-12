# ESP32 MPU6050 I2C 진단 스케치

`mpu6050_i2c_probe.ino`는 실장비 배선 문제를 좁히기 위한 read-only 진단용이다.
Device Service Runtime이나 운영 firmware가 아니다.

다음 ESP32 SDA/SCL 후보만 순서대로 초기화하고 MPU6050 주소 `0x68`, `0x69`에 ACK와
`WHO_AM_I(0x75)`를 요청한다.

```text
21/22, 4/5, 18/19, 25/26, 32/33,
16/17, 26/27, 27/26, 13/14
```

주소 전체를 scan하지 않고 MPU6050의 두 주소만 확인한다. 출력 예:

```json
{"type":"i2c_probe","sda":21,"scl":22,"address":"0x68","ack":false}
```

진단 후에는 반드시 `../mpu6050_json/mpu6050_json.ino` 운영 firmware를 다시
업로드한다. dev0003에는 진단 뒤 운영 firmware를 복원했으며, 2026-07-28 점검에서는 모든
조합이 `ack:false`였다.
