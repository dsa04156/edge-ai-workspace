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
