void setup() {
  Serial.begin(115200);
}

void loop() {
  int light = analogRead(A0);
  int temperature_raw = analogRead(A1);
  int magnetic = digitalRead(4);

  int accel_x = analogRead(A2);
  int accel_y = analogRead(A3);
  int accel_z = analogRead(A4);

  Serial.print("{\"device_id\":\"arduino-001\",\"sensor\":\"light\",\"value\":");
  Serial.print(light);
  Serial.println("}");

  Serial.print("{\"device_id\":\"arduino-001\",\"sensor\":\"temperature\",\"raw\":");
  Serial.print(temperature_raw);
  Serial.println("}");

  Serial.print("{\"device_id\":\"arduino-001\",\"sensor\":\"magnetic\",\"value\":");
  Serial.print(magnetic);
  Serial.println("}");

  Serial.print("{\"device_id\":\"arduino-001\",\"sensor\":\"acceleration\",\"x\":");
  Serial.print(accel_x);
  Serial.print(",\"y\":");
  Serial.print(accel_y);
  Serial.print(",\"z\":");
  Serial.print(accel_z);
  Serial.println("}");

  delay(1000);
}
