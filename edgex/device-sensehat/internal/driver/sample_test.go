package driver

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

const validSampleLine = `{"device_id":"sensehat-001","origin":123456789,"temp_humidity":39.5,"temp_pressure":36.5,"humidity":35.25,"pressure":1005.125,"compass":345.0,"pitch":358.0,"roll":359.0,"yaw":345.0,"gyro_x":0.1,"gyro_y":0.2,"gyro_z":-0.3}`

func TestParseSampleAcceptsCompleteFiniteReading(t *testing.T) {
	sample, err := ParseSample([]byte(validSampleLine), "sensehat-001")
	require.NoError(t, err)

	assert.Equal(t, "sensehat-001", sample.DeviceID)
	assert.Equal(t, int64(123456789), sample.Origin)
	assert.Equal(t, 39.5, sample.TempHumidity)
	assert.Equal(t, 1005.125, sample.Pressure)
	assert.Equal(t, -0.3, sample.GyroZ)
	assert.Equal(t, map[string]float64{
		"temp_humidity": 39.5,
		"temp_pressure": 36.5,
		"humidity":      35.25,
		"pressure":      1005.125,
		"compass":       345.0,
		"pitch":         358.0,
		"roll":          359.0,
		"yaw":           345.0,
		"gyro_x":        0.1,
		"gyro_y":        0.2,
		"gyro_z":        -0.3,
	}, sample.ResourceValues())
}

func TestParseSampleRejectsWrongIdentityMissingFieldsAndTrailingData(t *testing.T) {
	_, err := ParseSample([]byte(validSampleLine), "other-sensehat")
	assert.ErrorContains(t, err, "unexpected physical device")

	_, err = ParseSample([]byte(`{"device_id":"sensehat-001","origin":1}`), "sensehat-001")
	assert.ErrorContains(t, err, "temp_humidity")

	_, err = ParseSample([]byte(validSampleLine+` {}`), "sensehat-001")
	assert.ErrorContains(t, err, "trailing")

	_, err = ParseSample([]byte(`{"device_id":"sensehat-001","origin":0,"temp_humidity":1,"temp_pressure":1,"humidity":1,"pressure":1,"compass":1,"pitch":1,"roll":1,"yaw":1,"gyro_x":1,"gyro_y":1,"gyro_z":1}`), "sensehat-001")
	assert.ErrorContains(t, err, "origin")
}

func TestParseSampleRejectsUnknownFields(t *testing.T) {
	_, err := ParseSample([]byte(validSampleLine[:len(validSampleLine)-1]+`,"mqtt_topic":"legacy"}`), "sensehat-001")
	assert.ErrorContains(t, err, "unknown field")
}
