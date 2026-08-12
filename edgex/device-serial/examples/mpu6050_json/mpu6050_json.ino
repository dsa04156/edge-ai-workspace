#include <Wire.h>

namespace {

constexpr uint8_t kAddressPrimary = 0x68;
constexpr uint8_t kAddressSecondary = 0x69;
constexpr uint8_t kWhoAmIRegister = 0x75;
constexpr uint8_t kPowerManagementRegister = 0x6B;
constexpr uint8_t kFirstMeasurementRegister = 0x3B;
#if defined(ARDUINO_ARCH_ESP32)
constexpr uint8_t kSdaPin = 21;
constexpr uint8_t kSclPin = 22;
#endif
constexpr float kGravity = 9.80665F;
constexpr float kDegreesToRadians = 0.017453292519943295F;
constexpr unsigned long kSampleIntervalMs = 100;

uint8_t sensorAddress = 0;
unsigned long lastSampleAt = 0;
unsigned long lastProbeAt = 0;

bool readRegisters(uint8_t address, uint8_t firstRegister, uint8_t *buffer, size_t length) {
  Wire.beginTransmission(address);
  Wire.write(firstRegister);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(address, static_cast<uint8_t>(length), static_cast<uint8_t>(true)) != length) {
    return false;
  }
  for (size_t index = 0; index < length; ++index) {
    buffer[index] = Wire.read();
  }
  return true;
}

bool writeRegister(uint8_t address, uint8_t targetRegister, uint8_t value) {
  Wire.beginTransmission(address);
  Wire.write(targetRegister);
  Wire.write(value);
  return Wire.endTransmission(true) == 0;
}

bool identify(uint8_t address) {
  uint8_t identity = 0;
  return readRegisters(address, kWhoAmIRegister, &identity, 1)
      && (identity == kAddressPrimary || identity == kAddressSecondary);
}

bool selectSensor() {
  if (identify(kAddressPrimary)) {
    sensorAddress = kAddressPrimary;
  } else if (identify(kAddressSecondary)) {
    sensorAddress = kAddressSecondary;
  } else {
    sensorAddress = 0;
    return false;
  }
  if (!writeRegister(sensorAddress, kPowerManagementRegister, 0x00)) {
    sensorAddress = 0;
    return false;
  }
  delay(100);
  return true;
}

void printIdentity(uint8_t address) {
  uint8_t identity = 0;
  if (!readRegisters(address, kWhoAmIRegister, &identity, 1)) {
    Serial.print(F("null"));
    return;
  }
  Serial.print(identity);
}

void emitProbeFailure() {
  Serial.print(F("{\"type\":\"status\",\"device_id\":\"mpu6050-001\","));
  Serial.print(F("\"status\":\"sensor_not_found\",\"who_am_i_0x68\":"));
  printIdentity(kAddressPrimary);
  Serial.print(F(",\"who_am_i_0x69\":"));
  printIdentity(kAddressSecondary);
  Serial.println(F("}"));
}

int16_t signedWord(const uint8_t *buffer, size_t offset) {
  return static_cast<int16_t>(
      (static_cast<uint16_t>(buffer[offset]) << 8) | buffer[offset + 1]);
}

bool emitTelemetry() {
  uint8_t measurement[14];
  if (!readRegisters(sensorAddress, kFirstMeasurementRegister, measurement, sizeof(measurement))) {
    return false;
  }

  const float accelerationX = signedWord(measurement, 0) / 16384.0F * kGravity;
  const float accelerationY = signedWord(measurement, 2) / 16384.0F * kGravity;
  const float accelerationZ = signedWord(measurement, 4) / 16384.0F * kGravity;
  const float gyroX = signedWord(measurement, 8) / 131.0F * kDegreesToRadians;
  const float gyroY = signedWord(measurement, 10) / 131.0F * kDegreesToRadians;
  const float gyroZ = signedWord(measurement, 12) / 131.0F * kDegreesToRadians;

  Serial.print(F("{\"device_id\":\"mpu6050-001\",\"sensor\":\"imu\","));
  Serial.print(F("\"acceleration_x\":"));
  Serial.print(accelerationX, 6);
  Serial.print(F(",\"acceleration_y\":"));
  Serial.print(accelerationY, 6);
  Serial.print(F(",\"acceleration_z\":"));
  Serial.print(accelerationZ, 6);
  Serial.print(F(",\"gyro_x\":"));
  Serial.print(gyroX, 6);
  Serial.print(F(",\"gyro_y\":"));
  Serial.print(gyroY, 6);
  Serial.print(F(",\"gyro_z\":"));
  Serial.print(gyroZ, 6);
  Serial.println(F("}"));
  return true;
}

}  // namespace

void setup() {
  Serial.begin(115200);
#if defined(ARDUINO_ARCH_ESP32)
  Wire.begin(kSdaPin, kSclPin);
#else
  Wire.begin();
#endif
  delay(250);
  selectSensor();
}

void loop() {
  const unsigned long now = millis();
  if (sensorAddress == 0) {
    if (now - lastProbeAt >= 1000) {
      lastProbeAt = now;
      if (!selectSensor()) {
        emitProbeFailure();
      }
    }
    return;
  }
  if (now - lastSampleAt < kSampleIntervalMs) {
    return;
  }
  lastSampleAt = now;
  if (!emitTelemetry()) {
    sensorAddress = 0;
    lastProbeAt = now;
  }
}
