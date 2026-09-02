const unsigned long kSampleIntervalMs = 1000;
const char kReadNowCommand[] = "READ_NOW";
const size_t kCommandBufferSize = 24;

char commandBuffer[kCommandBufferSize];
size_t commandLength = 0;
unsigned long lastSampleAt = 0;

void emitSample() {
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
}

void handleCommandByte(char value) {
  if (value == '\r') {
    return;
  }
  if (value == '\n') {
    commandBuffer[commandLength] = '\0';
    if (strcmp(commandBuffer, kReadNowCommand) == 0) {
      emitSample();
      lastSampleAt = millis();
    }
    commandLength = 0;
    return;
  }
  if (commandLength + 1 < kCommandBufferSize) {
    commandBuffer[commandLength++] = value;
    return;
  }
  commandLength = 0;
}

void setup() {
  Serial.begin(115200);
  emitSample();
  lastSampleAt = millis();
}

void loop() {
  while (Serial.available() > 0) {
    handleCommandByte(static_cast<char>(Serial.read()));
  }

  unsigned long now = millis();
  if (now - lastSampleAt >= kSampleIntervalMs) {
    emitSample();
    lastSampleAt = now;
  }
}
