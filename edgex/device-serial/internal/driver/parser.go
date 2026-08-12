package driver

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
)

type Reading struct {
	ResourceName string
	Value        int32
	FloatValue   *float64
}

type Sample struct {
	DeviceName string
	SourceName string
	Readings   []Reading
}

type wireSample struct {
	DeviceID string           `json:"device_id"`
	Sensor   string           `json:"sensor"`
	Raw      *json.RawMessage `json:"raw"`
	Value    *json.RawMessage `json:"value"`
	X        *json.RawMessage `json:"x"`
	Y        *json.RawMessage `json:"y"`
	Z        *json.RawMessage `json:"z"`
}

func ParseLine(line []byte, expectedDevice string) (Sample, error) {
	return ParseLineWithParser(line, expectedDevice, defaultSerialParser)
}

func ParseLineWithParser(
	line []byte,
	expectedDevice string,
	parser string,
) (Sample, error) {
	switch normalizedSerialParser(parser) {
	case defaultSerialParser:
		return parseArduinoMultisensorLine(line, expectedDevice)
	case mpu6050SerialParser:
		return parseMPU6050Line(line, expectedDevice)
	default:
		return Sample{}, fmt.Errorf("unsupported serial parser %q", parser)
	}
}

func parseArduinoMultisensorLine(line []byte, expectedDevice string) (Sample, error) {
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	var wire wireSample
	if err := decoder.Decode(&wire); err != nil {
		return Sample{}, fmt.Errorf("invalid serial JSON: %w", err)
	}
	if err := ensureJSONEOF(decoder); err != nil {
		return Sample{}, err
	}
	if wire.DeviceID != expectedDevice {
		return Sample{}, fmt.Errorf("unexpected device_id %q", wire.DeviceID)
	}

	readings, err := wire.readings()
	if err != nil {
		return Sample{}, err
	}
	return Sample{
		DeviceName: wire.DeviceID,
		SourceName: wire.Sensor,
		Readings:   readings,
	}, nil
}

type mpu6050WireSample struct {
	DeviceID      string   `json:"device_id"`
	Sensor        string   `json:"sensor"`
	AccelerationX *float64 `json:"acceleration_x"`
	AccelerationY *float64 `json:"acceleration_y"`
	AccelerationZ *float64 `json:"acceleration_z"`
	GyroX         *float64 `json:"gyro_x"`
	GyroY         *float64 `json:"gyro_y"`
	GyroZ         *float64 `json:"gyro_z"`
}

func parseMPU6050Line(line []byte, expectedDevice string) (Sample, error) {
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	var wire mpu6050WireSample
	if err := decoder.Decode(&wire); err != nil {
		return Sample{}, fmt.Errorf("invalid MPU6050 serial JSON: %w", err)
	}
	if err := ensureJSONEOF(decoder); err != nil {
		return Sample{}, err
	}
	if wire.DeviceID != expectedDevice {
		return Sample{}, fmt.Errorf("unexpected device_id %q", wire.DeviceID)
	}
	if wire.Sensor != "imu" {
		return Sample{}, fmt.Errorf("MPU6050 sensor must be %q", "imu")
	}

	values := []struct {
		name  string
		value *float64
	}{
		{name: "acceleration_x", value: wire.AccelerationX},
		{name: "acceleration_y", value: wire.AccelerationY},
		{name: "acceleration_z", value: wire.AccelerationZ},
		{name: "gyro_x", value: wire.GyroX},
		{name: "gyro_y", value: wire.GyroY},
		{name: "gyro_z", value: wire.GyroZ},
	}
	readings := make([]Reading, 0, len(values))
	for _, item := range values {
		if item.value == nil {
			return Sample{}, fmt.Errorf("%s is required", item.name)
		}
		if math.IsNaN(*item.value) || math.IsInf(*item.value, 0) {
			return Sample{}, fmt.Errorf("%s must be finite", item.name)
		}
		value := *item.value
		readings = append(readings, Reading{
			ResourceName: item.name,
			FloatValue:   &value,
		})
	}
	return Sample{
		DeviceName: wire.DeviceID,
		SourceName: wire.Sensor,
		Readings:   readings,
	}, nil
}

func (reading Reading) typedValue(valueType string) (any, error) {
	switch valueType {
	case "Int32":
		if reading.FloatValue != nil {
			return nil, fmt.Errorf("%s contains a floating-point value", reading.ResourceName)
		}
		return reading.Value, nil
	case "Float64":
		if reading.FloatValue == nil {
			return nil, fmt.Errorf("%s does not contain a Float64 value", reading.ResourceName)
		}
		return *reading.FloatValue, nil
	default:
		return nil, fmt.Errorf("unsupported serial value type %q", valueType)
	}
}

func ensureJSONEOF(decoder *json.Decoder) error {
	var trailing any
	err := decoder.Decode(&trailing)
	if errors.Is(err, io.EOF) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("invalid trailing serial JSON: %w", err)
	}
	return errors.New("serial line contains more than one JSON value")
}

func (wire wireSample) readings() ([]Reading, error) {
	switch wire.Sensor {
	case "temperature":
		if wire.Raw == nil || wire.Value != nil || wire.X != nil || wire.Y != nil || wire.Z != nil {
			return nil, errors.New("temperature requires only raw")
		}
		value, err := int32Value("raw", wire.Raw)
		if err != nil {
			return nil, err
		}
		return []Reading{{ResourceName: "temperature_raw", Value: value}}, nil
	case "light", "magnetic":
		if wire.Value == nil || wire.Raw != nil || wire.X != nil || wire.Y != nil || wire.Z != nil {
			return nil, fmt.Errorf("%s requires only value", wire.Sensor)
		}
		value, err := int32Value("value", wire.Value)
		if err != nil {
			return nil, err
		}
		return []Reading{{ResourceName: wire.Sensor + "_raw", Value: value}}, nil
	case "acceleration":
		if wire.X == nil || wire.Y == nil || wire.Z == nil || wire.Raw != nil || wire.Value != nil {
			return nil, errors.New("acceleration requires only x, y and z")
		}
		x, err := int32Value("x", wire.X)
		if err != nil {
			return nil, err
		}
		y, err := int32Value("y", wire.Y)
		if err != nil {
			return nil, err
		}
		z, err := int32Value("z", wire.Z)
		if err != nil {
			return nil, err
		}
		return []Reading{
			{ResourceName: "acceleration_x_raw", Value: x},
			{ResourceName: "acceleration_y_raw", Value: y},
			{ResourceName: "acceleration_z_raw", Value: z},
		}, nil
	default:
		return nil, fmt.Errorf("unsupported sensor %q", wire.Sensor)
	}
}

func int32Value(field string, raw *json.RawMessage) (int32, error) {
	if raw == nil {
		return 0, fmt.Errorf("%s is required", field)
	}
	value, err := strconv.ParseInt(string(*raw), 10, 32)
	if err != nil {
		return 0, fmt.Errorf("%s must be an integer: %w", field, err)
	}
	return int32(value), nil
}
