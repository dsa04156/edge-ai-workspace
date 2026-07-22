package driver

import (
	"errors"
	"fmt"
	"path/filepath"
	"strconv"
	"strings"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
)

const supportedBaudRate = 115200

type SerialConfig struct {
	Port         string
	BaudRate     int
	DeviceID     string
	ResourceName string
}

type connectionKey struct {
	port     string
	baudRate int
	deviceID string
}

func (config SerialConfig) key() connectionKey {
	return connectionKey{
		port:     config.Port,
		baudRate: config.BaudRate,
		deviceID: config.DeviceID,
	}
}

func ParseSerialConfig(protocols map[string]models.ProtocolProperties) (SerialConfig, error) {
	properties, ok := protocols["serial"]
	if !ok {
		return SerialConfig{}, errors.New("serial protocol is required")
	}

	port, err := requiredString(properties, "Port")
	if err != nil {
		return SerialConfig{}, err
	}
	if !filepath.IsAbs(port) {
		return SerialConfig{}, fmt.Errorf("serial Port must be absolute: %q", port)
	}

	baudRate, err := baudRateValue(properties["BaudRate"])
	if err != nil {
		return SerialConfig{}, err
	}
	if baudRate != supportedBaudRate {
		return SerialConfig{}, fmt.Errorf("unsupported serial BaudRate %d; expected %d", baudRate, supportedBaudRate)
	}

	deviceID, err := requiredString(properties, "DeviceID")
	if err != nil {
		return SerialConfig{}, err
	}

	resourceName, err := requiredString(properties, "ResourceName")
	if err != nil {
		return SerialConfig{}, err
	}
	if _, ok := supportedResources[resourceName]; !ok {
		return SerialConfig{}, fmt.Errorf("unsupported serial ResourceName %q", resourceName)
	}

	return SerialConfig{
		Port:         port,
		BaudRate:     baudRate,
		DeviceID:     deviceID,
		ResourceName: resourceName,
	}, nil
}

func requiredString(properties models.ProtocolProperties, name string) (string, error) {
	raw, ok := properties[name]
	if !ok {
		return "", fmt.Errorf("serial %s is required", name)
	}
	value, ok := raw.(string)
	if !ok {
		return "", fmt.Errorf("serial %s must be a string", name)
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return "", fmt.Errorf("serial %s must not be empty", name)
	}
	return value, nil
}

func baudRateValue(raw any) (int, error) {
	switch value := raw.(type) {
	case int:
		return value, nil
	case int32:
		return int(value), nil
	case int64:
		return int(value), nil
	case float64:
		if value != float64(int(value)) {
			return 0, fmt.Errorf("serial BaudRate must be an integer, got %v", value)
		}
		return int(value), nil
	case string:
		parsed, err := strconv.Atoi(strings.TrimSpace(value))
		if err != nil {
			return 0, fmt.Errorf("serial BaudRate must be an integer: %w", err)
		}
		return parsed, nil
	case nil:
		return 0, errors.New("serial BaudRate is required")
	default:
		return 0, fmt.Errorf("serial BaudRate has unsupported type %T", raw)
	}
}
