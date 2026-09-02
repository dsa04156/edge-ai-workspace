package driver

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestArduinoUnoMultisensorFirmwarePreservesWireAndPinContract(t *testing.T) {
	contents, err := os.ReadFile("../../firmware/arduino_uno_multisensor/arduino_uno_multisensor.ino")
	require.NoError(t, err)
	source := string(contents)

	for _, expected := range []string{
		"Serial.begin(115200)",
		"analogRead(A0)",
		"analogRead(A1)",
		"digitalRead(4)",
		"analogRead(A2)",
		"analogRead(A3)",
		"analogRead(A4)",
		`\"device_id\":\"arduino-001\"`,
		`\"sensor\":\"light\"`,
		`\"sensor\":\"temperature\"`,
		`\"sensor\":\"magnetic\"`,
		`\"sensor\":\"acceleration\"`,
	} {
		assert.Contains(t, source, expected)
	}
}

func TestArduinoUnoMultisensorFirmwareUsesOnDemandRecoveryWithOneSecondBaseline(t *testing.T) {
	contents, err := os.ReadFile("../../firmware/arduino_uno_multisensor/arduino_uno_multisensor.ino")
	require.NoError(t, err)
	source := string(contents)

	assert.Contains(t, source, "kSampleIntervalMs = 1000")
	assert.Contains(t, source, `kReadNowCommand[] = "READ_NOW"`)
	assert.Contains(t, source, "Serial.available()")
	assert.Contains(t, source, "emitSample()")
	assert.NotContains(t, source, "delay(100)")
}
