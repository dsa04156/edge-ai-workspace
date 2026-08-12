#include <Wire.h>

namespace {

constexpr uint8_t kAddresses[] = {0x68, 0x69};
constexpr uint8_t kWhoAmIRegister = 0x75;

struct PinPair {
  uint8_t sda;
  uint8_t scl;
};

constexpr PinPair kPinPairs[] = {
    {21, 22},
    {4, 5},
    {18, 19},
    {25, 26},
    {32, 33},
    {16, 17},
    {26, 27},
    {27, 26},
    {13, 14},
};

void printAddress(uint8_t value) {
  Serial.print(F("\"0x"));
  if (value < 0x10) {
    Serial.print('0');
  }
  Serial.print(value, HEX);
  Serial.print('"');
}

void probe(uint8_t address, const PinPair &pins) {
  Wire.beginTransmission(address);
  const uint8_t error = Wire.endTransmission(true);

  Serial.print(F("{\"type\":\"i2c_probe\",\"sda\":"));
  Serial.print(pins.sda);
  Serial.print(F(",\"scl\":"));
  Serial.print(pins.scl);
  Serial.print(F(",\"address\":"));
  printAddress(address);
  Serial.print(F(",\"ack\":"));
  Serial.print(error == 0 ? F("true") : F("false"));

  if (error == 0) {
    Wire.beginTransmission(address);
    Wire.write(kWhoAmIRegister);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(address, 1U, true) == 1) {
      Serial.print(F(",\"who_am_i\":"));
      printAddress(Wire.read());
    }
  }
  Serial.println('}');
}

void scan() {
  for (const PinPair &pins : kPinPairs) {
    Wire.end();
    Wire.begin(pins.sda, pins.scl);
    Wire.setClock(100000);
    delay(20);
    for (uint8_t address : kAddresses) {
      probe(address, pins);
    }
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  scan();
}

void loop() {
  delay(5000);
  scan();
}
