package driver

import (
	"fmt"
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
		Port:             "/dev/arduino-001",
		BaudRate:         115200,
		DeviceID:         "arduino-001",
		Parser:           defaultSerialParser,
		ResourceName:     "temperature_raw",
		RecoveryStrategy: passiveFirstDataRecoveryStrategy,
	}, config)
}

func TestParseSerialConfigAcceptsOnDemandRecovery(t *testing.T) {
	protocols := map[string]models.ProtocolProperties{
		"serial": {
			"Port":             "/dev/arduino-001",
			"BaudRate":         "115200",
			"DeviceID":         "arduino-001",
			"ResourceName":     "temperature_raw",
			"RecoveryStrategy": onDemandReadRecoveryStrategy,
		},
	}

	config, err := ParseSerialConfig(protocols)

	require.NoError(t, err)
	assert.Equal(t, onDemandReadRecoveryStrategy, config.RecoveryStrategy)
}

func TestParseSerialConfigAcceptsAggregateResourceWildcard(t *testing.T) {
	config, err := ParseSerialConfig(map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/arduino-002",
			"BaudRate":     "115200",
			"DeviceID":     "arduino-002",
			"ResourceName": "*",
		},
	})

	require.NoError(t, err)
	assert.Equal(t, "*", config.ResourceName)
	assert.Equal(t, defaultSerialParser, config.Parser)
	assert.Equal(t, allSupportedResources, config.resourceNames())
}

func TestParseSerialConfigAcceptsMPU6050Parser(t *testing.T) {
	config, err := ParseSerialConfig(map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/mpu6050-001",
			"BaudRate":     115200,
			"DeviceID":     "mpu6050-001",
			"Parser":       mpu6050SerialParser,
			"ResourceName": "*",
		},
	})

	require.NoError(t, err)
	assert.Equal(t, mpu6050SerialParser, config.Parser)
	assert.Equal(t, []string{
		"acceleration_x",
		"acceleration_y",
		"acceleration_z",
		"gyro_x",
		"gyro_y",
		"gyro_z",
	}, config.resourceNames())
}

func TestParseSerialConfigAcceptsSupportedNumericBaudRates(t *testing.T) {
	for _, baudRate := range []int{9600, 57600, 115200, 921600} {
		t.Run(fmt.Sprintf("%d", baudRate), func(t *testing.T) {
			protocols := map[string]models.ProtocolProperties{
				"serial": {
					"Port":         "/dev/arduino-001",
					"BaudRate":     baudRate,
					"DeviceID":     "arduino-001",
					"ResourceName": "light_raw",
				},
			}

			config, err := ParseSerialConfig(protocols)

			require.NoError(t, err)
			assert.Equal(t, baudRate, config.BaudRate)
			assert.Equal(t, "light_raw", config.ResourceName)
		})
	}
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
				"Port": "/dev/arduino-001", "BaudRate": "12345", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
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
			name: "unsupported parser",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "DeviceID": "arduino-001", "Parser": "unknown", "ResourceName": "*",
			}},
		},
		{
			name: "resource not supported by selected parser",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "DeviceID": "arduino-001", "Parser": mpu6050SerialParser, "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "invalid property type",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": true, "BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "temperature_raw",
			}},
		},
		{
			name: "unsupported recovery strategy",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/arduino-001", "BaudRate": "115200", "DeviceID": "arduino-001", "ResourceName": "temperature_raw", "RecoveryStrategy": "arbitrary-command",
			}},
		},
		{
			name: "on demand recovery unsupported by parser",
			protocols: map[string]models.ProtocolProperties{"serial": {
				"Port": "/dev/mpu6050-001", "BaudRate": "115200", "DeviceID": "mpu6050-001", "Parser": mpu6050SerialParser, "ResourceName": "*", "RecoveryStrategy": onDemandReadRecoveryStrategy,
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
