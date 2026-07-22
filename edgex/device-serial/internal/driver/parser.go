package driver

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
)

type Reading struct {
	ResourceName string
	Value        int32
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
