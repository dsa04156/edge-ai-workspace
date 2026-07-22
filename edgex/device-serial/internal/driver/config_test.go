package driver

import (
	"testing"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParseSerialConfig(t *testing.T) {
	protocols := map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/arduino-001",
			"BaudRate":     "115200",
			"DeviceID":     "arduino-001",
			"ResourceName": "temperature_raw",
		},
	}

	config, err := ParseSerialConfig(protocols)

	require.NoError(t, err)
	assert.Equal(t, SerialConfig{
		Port:         "/dev/arduino-001",
		BaudRate:     115200,
		DeviceID:     "arduino-001",
		ResourceName: "temperature_raw",
	}, config)
}

func TestParseSerialConfigAcceptsNumericBaudRate(t *testing.T) {
	protocols := map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/arduino-001",
			"BaudRate":     115200,
			"DeviceID":     "arduino-001",
			"ResourceName": "light_raw",
		},
	}

	config, err := ParseSerialConfig(protocols)

	require.NoError(t, err)
	assert.Equal(t, 115200, config.BaudRate)
	assert.Equal(t, "light_raw", config.ResourceName)
}

func TestParseSerialConfigRejectsUnsafeOrIncompleteProperties(t *testing.T) {
	tests := []struct {
		name      string
		protocols map[string]models.ProtocolProperties
	}{
		{name: "missing serial protocol", protocols: map[string]models.ProtocolProperties{}},
		{
			name: "relative port",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "ttyACM0", "BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "missing port",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "unsupported baud rate",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "9600", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "non numeric baud rate",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "fast", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "missing device id",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "missing resource name",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "DeviceID": "arduino-001",
			}},
		},
		{
			name: "unsupported resource name",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "pressure_raw",
			}},
		},
		{
			name: "invalid property type",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": true, "BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := ParseSerialConfig(test.protocols)
			assert.Error(t, err)
		})
	}
}
