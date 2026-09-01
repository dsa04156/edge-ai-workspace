package driver

import (
	"os"
	"regexp"
	"strconv"
	"strings"
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

func TestArduinoUnoMultisensorFirmwareBoundsSamplingInterval(t *testing.T) {
	contents, err := os.ReadFile("../../firmware/arduino_uno_multisensor/arduino_uno_multisensor.ino")
	require.NoError(t, err)

	match := regexp.MustCompile(`delay\((\d+)\);`).FindStringSubmatch(string(contents))
	require.Len(t, match, 2, "firmware must use an explicit bounded delay")
	interval, err := strconv.Atoi(strings.TrimSpace(match[1]))
	require.NoError(t, err)
	assert.LessOrEqual(t, interval, 100)
}
