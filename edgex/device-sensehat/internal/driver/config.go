package driver

import (
	"errors"
	"fmt"
	"strings"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
)

const (
	supportedI2CBus  = "/dev/i2c-1"
	senseHatDeviceID = "sensehat-001"
)

var resourceGroups = map[string][]string{
	"temperature": {"temp_humidity", "temp_pressure"},
	"humidity":    {"humidity"},
	"pressure":    {"pressure"},
	"compass":     {"compass"},
	"orientation": {"pitch", "roll", "yaw"},
	"gyroscope":   {"gyro_x", "gyro_y", "gyro_z"},
}

type I2CConfig struct {
	Bus           string
	DeviceID      string
	ResourceGroup string
}

type connectionKey struct {
	bus      string
	deviceID string
}

func (config I2CConfig) key() connectionKey {
	return connectionKey{bus: config.Bus, deviceID: config.DeviceID}
}

func ParseI2CConfig(protocols map[string]models.ProtocolProperties) (I2CConfig, error) {
	properties, ok := protocols["i2c"]
	if !ok {
		return I2CConfig{}, errors.New("i2c protocol is required")
	}
	bus, err := requiredI2CString(properties, "Bus")
	if err != nil {
		return I2CConfig{}, err
	}
	if bus != supportedI2CBus {
		return I2CConfig{}, fmt.Errorf("unsupported i2c Bus %q; expected %q", bus, supportedI2CBus)
	}
	deviceID, err := requiredI2CString(properties, "DeviceID")
	if err != nil {
		return I2CConfig{}, err
	}
	if deviceID != senseHatDeviceID {
		return I2CConfig{}, fmt.Errorf("unsupported i2c DeviceID %q; expected %q", deviceID, senseHatDeviceID)
	}
	group, err := requiredI2CString(properties, "ResourceGroup")
	if err != nil {
		return I2CConfig{}, err
	}
	if _, ok := resourceGroups[group]; !ok {
		return I2CConfig{}, fmt.Errorf("unsupported i2c ResourceGroup %q", group)
	}
	return I2CConfig{Bus: bus, DeviceID: deviceID, ResourceGroup: group}, nil
}

func requiredI2CString(properties models.ProtocolProperties, name string) (string, error) {
	raw, ok := properties[name]
	if !ok {
		return "", fmt.Errorf("i2c %s is required", name)
	}
	value, ok := raw.(string)
	if !ok {
		return "", fmt.Errorf("i2c %s must be a string", name)
	}
	value = strings.TrimSpace(value)
	if value == "" {
		return "", fmt.Errorf("i2c %s must not be empty", name)
	}
	return value, nil
}
