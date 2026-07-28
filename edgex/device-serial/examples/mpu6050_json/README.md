# MPU6050 USB Serial 예제

Raspberry Pi에 연결된 Arduino/CH340 보드가 MPU6050 6축 값을
`device-serial`의 `mpu6050-imu-v1` parser 계약으로 전송하는 예제다.

- Serial: `115200 8N1`
- 물리 source ID: `mpu6050-001`
- MPU6050 주소: `0x68` 또는 `0x69`
- 가속도 단위: `m/s2`
- 각속도 단위: `rad/s`
- 출력: 한 줄에 JSON 객체 하나

Arduino IDE에서 `mpu6050_json.ino`를 보드에 업로드한다. 외부 MPU6050
라이브러리는 필요하지 않으며 `Wire`만 사용한다.

정상 출력 예:

```json
{"device_id":"mpu6050-001","sensor":"imu","acceleration_x":0.012000,"acceleration_y":-0.021000,"acceleration_z":9.801000,"gyro_x":0.001000,"gyro_y":-0.002000,"gyro_z":0.003000}
```

보드가 이 형식의 값을 보내기 전에는 Device Service를 배포할 수 있어도
EdgeX 첫 Event 확인 단계는 완료되지 않는다.
