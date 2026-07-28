package driver

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParseLineMapsMeasuredPayloads(t *testing.T) {
	tests := []struct {
		name     string
		line     string
		source   string
		readings []Reading
	}{
		{
			name:     "temperature",
			line:     `{"device_id":"arduino-001","sensor":"temperature","raw":297}`,
			source:   "temperature",
			readings: []Reading{{ResourceName: "temperature_raw", Value: 297}},
		},
		{
			name:     "light",
			line:     `{"device_id":"arduino-001","sensor":"light","value":304}`,
			source:   "light",
			readings: []Reading{{ResourceName: "light_raw", Value: 304}},
		},
		{
			name:     "magnetic",
			line:     `{"device_id":"arduino-001","sensor":"magnetic","value":0}`,
			source:   "magnetic",
			readings: []Reading{{ResourceName: "magnetic_raw", Value: 0}},
		},
		{
			name:   "acceleration",
			line:   `{"device_id":"arduino-001","sensor":"acceleration","x":298,"y":266,"z":278}`,
			source: "acceleration",
			readings: []Reading{
				{ResourceName: "acceleration_x_raw", Value: 298},
				{ResourceName: "acceleration_y_raw", Value: 266},
				{ResourceName: "acceleration_z_raw", Value: 278},
			},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := ParseLine([]byte(test.line), "arduino-001")

			require.NoError(t, err)
			assert.Equal(t, "arduino-001", got.DeviceName)
			assert.Equal(t, test.source, got.SourceName)
			assert.Equal(t, test.readings, got.Readings)
		})
	}
}

func TestParseLineAcceptsInt32Bounds(t *testing.T) {
	for _, value := range []int64{math.MinInt32, math.MaxInt32} {
		line := []byte(`{"device_id":"arduino-001","sensor":"temperature","raw":` +
			formatInt(value) + `}`)

		got, err := ParseLine(line, "arduino-001")

		require.NoError(t, err)
		assert.Equal(t, int32(value), got.Readings[0].Value)
	}
}

func TestParseLineWithMPU6050ParserMapsSixAxisSIValues(t *testing.T) {
	line := []byte(
		`{"device_id":"mpu6050-001","sensor":"imu",` +
			`"acceleration_x":0.125,"acceleration_y":-0.25,` +
			`"acceleration_z":9.80665,"gyro_x":0.01,` +
			`"gyro_y":-0.02,"gyro_z":0.03}`,
	)

	got, err := ParseLineWithParser(
		line,
		"mpu6050-001",
		mpu6050SerialParser,
	)

	require.NoError(t, err)
	assert.Equal(t, "mpu6050-001", got.DeviceName)
	assert.Equal(t, "imu", got.SourceName)
	require.Len(t, got.Readings, 6)
	assert.Equal(t, []string{
		"acceleration_x",
		"acceleration_y",
		"acceleration_z",
		"gyro_x",
		"gyro_y",
		"gyro_z",
	}, readingNames(got.Readings))
	assert.InDelta(t, 0.125, *got.Readings[0].FloatValue, 0.000001)
	assert.InDelta(t, 9.80665, *got.Readings[2].FloatValue, 0.000001)
	assert.InDelta(t, -0.02, *got.Readings[4].FloatValue, 0.000001)
}

func TestParseLineWithMPU6050ParserRejectsInvalidPayloads(t *testing.T) {
	validFields := `"acceleration_x":0.1,"acceleration_y":0.2,` +
		`"acceleration_z":9.8,"gyro_x":0.01,"gyro_y":0.02,"gyro_z":0.03`
	tests := []struct {
		name string
		line string
	}{
		{
			name: "wrong device",
			line: `{"device_id":"other","sensor":"imu",` + validFields + `}`,
		},
		{
			name: "wrong sensor",
			line: `{"device_id":"mpu6050-001","sensor":"acceleration",` + validFields + `}`,
		},
		{
			name: "missing axis",
			line: `{"device_id":"mpu6050-001","sensor":"imu",` +
				`"acceleration_x":0.1,"acceleration_y":0.2,` +
				`"gyro_x":0.01,"gyro_y":0.02,"gyro_z":0.03}`,
		},
		{
			name: "string value",
			line: `{"device_id":"mpu6050-001","sensor":"imu",` +
				`"acceleration_x":"0.1","acceleration_y":0.2,` +
				`"acceleration_z":9.8,"gyro_x":0.01,"gyro_y":0.02,"gyro_z":0.03}`,
		},
		{
			name: "unknown field",
			line: `{"device_id":"mpu6050-001","sensor":"imu",` +
				validFields + `,"temperature":25}`,
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := ParseLineWithParser(
				[]byte(test.line),
				"mpu6050-001",
				mpu6050SerialParser,
			)
			assert.Error(t, err)
		})
	}
}

func TestParseLineWithParserRejectsUnknownParser(t *testing.T) {
	_, err := ParseLineWithParser(
		[]byte(`{}`),
		"mpu6050-001",
		"unknown-parser",
	)
	assert.ErrorContains(t, err, "unsupported serial parser")
}

func TestParseLineRejectsInvalidPayloads(t *testing.T) {
	tests := []struct {
		name string
		line string
	}{
		{name: "empty", line: ""},
		{name: "partial object", line: `{"device_id":"arduino-001","sensor":"light","v}`},
		{name: "middle of object", line: `_id":"arduino-001","sensor":"magnetic","value":0}`},
		{name: "array root", line: `[]`},
		{name: "trailing object", line: `{"device_id":"arduino-001","sensor":"light","value":1}{}`},
		{name: "unknown field", line: `{"device_id":"arduino-001","sensor":"light","value":1,"unit":"lux"}`},
		{name: "wrong device", line: `{"device_id":"arduino-002","sensor":"light","value":1}`},
		{name: "unknown sensor", line: `{"device_id":"arduino-001","sensor":"pressure","value":1}`},
		{name: "missing temperature raw", line: `{"device_id":"arduino-001","sensor":"temperature"}`},
		{name: "mixed temperature fields", line: `{"device_id":"arduino-001","sensor":"temperature","raw":1,"value":1}`},
		{name: "missing acceleration z", line: `{"device_id":"arduino-001","sensor":"acceleration","x":1,"y":2}`},
		{name: "mixed acceleration fields", line: `{"device_id":"arduino-001","sensor":"acceleration","x":1,"y":2,"z":3,"value":4}`},
		{name: "float", line: `{"device_id":"arduino-001","sensor":"light","value":1.5}`},
		{name: "string", line: `{"device_id":"arduino-001","sensor":"light","value":"1"}`},
		{name: "boolean", line: `{"device_id":"arduino-001","sensor":"light","value":true}`},
		{name: "positive overflow", line: `{"device_id":"arduino-001","sensor":"light","value":2147483648}`},
		{name: "negative overflow", line: `{"device_id":"arduino-001","sensor":"light","value":-2147483649}`},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := ParseLine([]byte(test.line), "arduino-001")
			assert.Error(t, err)
		})
	}
}

func formatInt(value int64) string {
	if value == math.MinInt32 {
		return "-2147483648"
	}
	return "2147483647"
}

func readingNames(readings []Reading) []string {
	names := make([]string, len(readings))
	for index, reading := range readings {
		names[index] = reading.ResourceName
	}
	return names
}
