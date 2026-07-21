package driver

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
)

type Sample struct {
	DeviceID     string
	Origin       int64
	TempHumidity float64
	TempPressure float64
	Humidity     float64
	Pressure     float64
	Compass      float64
	Pitch        float64
	Roll         float64
	Yaw          float64
	GyroX        float64
	GyroY        float64
	GyroZ        float64
}

type sampleWire struct {
	DeviceID     *string  `json:"device_id"`
	Origin       *int64   `json:"origin"`
	TempHumidity *float64 `json:"temp_humidity"`
	TempPressure *float64 `json:"temp_pressure"`
	Humidity     *float64 `json:"humidity"`
	Pressure     *float64 `json:"pressure"`
	Compass      *float64 `json:"compass"`
	Pitch        *float64 `json:"pitch"`
	Roll         *float64 `json:"roll"`
	Yaw          *float64 `json:"yaw"`
	GyroX        *float64 `json:"gyro_x"`
	GyroY        *float64 `json:"gyro_y"`
	GyroZ        *float64 `json:"gyro_z"`
}

func ParseSample(line []byte, expectedDeviceID string) (Sample, error) {
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	var wire sampleWire
	if err := decoder.Decode(&wire); err != nil {
		return Sample{}, fmt.Errorf("decode Sense HAT sample: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); err != io.EOF {
		return Sample{}, fmt.Errorf("trailing JSON data in Sense HAT sample")
	}

	if wire.DeviceID == nil || *wire.DeviceID == "" {
		return Sample{}, fmt.Errorf("device_id is required")
	}
	if *wire.DeviceID != expectedDeviceID {
		return Sample{}, fmt.Errorf(
			"unexpected physical device %q; expected %q",
			*wire.DeviceID,
			expectedDeviceID,
		)
	}
	if wire.Origin == nil || *wire.Origin <= 0 {
		return Sample{}, fmt.Errorf("origin must be a positive nanosecond timestamp")
	}

	fields := []struct {
		name  string
		value *float64
	}{
		{"temp_humidity", wire.TempHumidity},
		{"temp_pressure", wire.TempPressure},
		{"humidity", wire.Humidity},
		{"pressure", wire.Pressure},
		{"compass", wire.Compass},
		{"pitch", wire.Pitch},
		{"roll", wire.Roll},
		{"yaw", wire.Yaw},
		{"gyro_x", wire.GyroX},
		{"gyro_y", wire.GyroY},
		{"gyro_z", wire.GyroZ},
	}
	for _, field := range fields {
		if field.value == nil {
			return Sample{}, fmt.Errorf("%s is required", field.name)
		}
		if math.IsNaN(*field.value) || math.IsInf(*field.value, 0) {
			return Sample{}, fmt.Errorf("%s must be finite", field.name)
		}
	}

	return Sample{
		DeviceID:     *wire.DeviceID,
		Origin:       *wire.Origin,
		TempHumidity: *wire.TempHumidity,
		TempPressure: *wire.TempPressure,
		Humidity:     *wire.Humidity,
		Pressure:     *wire.Pressure,
		Compass:      *wire.Compass,
		Pitch:        *wire.Pitch,
		Roll:         *wire.Roll,
		Yaw:          *wire.Yaw,
		GyroX:        *wire.GyroX,
		GyroY:        *wire.GyroY,
		GyroZ:        *wire.GyroZ,
	}, nil
}

func (sample Sample) ResourceValues() map[string]float64 {
	return map[string]float64{
		"temp_humidity": sample.TempHumidity,
		"temp_pressure": sample.TempPressure,
		"humidity":      sample.Humidity,
		"pressure":      sample.Pressure,
		"compass":       sample.Compass,
		"pitch":         sample.Pitch,
		"roll":          sample.Roll,
		"yaw":           sample.Yaw,
		"gyro_x":        sample.GyroX,
		"gyro_y":        sample.GyroY,
		"gyro_z":        sample.GyroZ,
	}
}
