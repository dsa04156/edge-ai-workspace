package driver

import (
	"testing"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func testI2CProtocols(group string) map[string]models.ProtocolProperties {
	return map[string]models.ProtocolProperties{
		"i2c": {
			"Bus":           "/dev/i2c-1",
			"DeviceID":      "sensehat-001",
			"ResourceGroup": group,
		},
	}
}

func TestParseI2CConfigAcceptsKnownSenseHatGroup(t *testing.T) {
	config, err := ParseI2CConfig(testI2CProtocols("orientation"))
	require.NoError(t, err)
	assert.Equal(t, I2CConfig{
		Bus:           "/dev/i2c-1",
		DeviceID:      "sensehat-001",
		ResourceGroup: "orientation",
	}, config)
	assert.Equal(t, connectionKey{bus: "/dev/i2c-1", deviceID: "sensehat-001"}, config.key())
}

func TestParseI2CConfigRejectsUnsupportedBindings(t *testing.T) {
	for name, mutate := range map[string]func(map[string]models.ProtocolProperties){
		"missing protocol": func(protocols map[string]models.ProtocolProperties) { delete(protocols, "i2c") },
		"wrong bus":        func(protocols map[string]models.ProtocolProperties) { protocols["i2c"]["Bus"] = "/dev/i2c-9" },
		"wrong device":     func(protocols map[string]models.ProtocolProperties) { protocols["i2c"]["DeviceID"] = "other" },
		"wrong group": func(protocols map[string]models.ProtocolProperties) {
			protocols["i2c"]["ResourceGroup"] = "acceleration"
		},
	} {
		t.Run(name, func(t *testing.T) {
			protocols := testI2CProtocols("temperature")
			mutate(protocols)
			_, err := ParseI2CConfig(protocols)
			assert.Error(t, err)
		})
	}
}

func TestResourceGroupsCoverEachSenseHatResourceExactlyOnce(t *testing.T) {
	expected := map[string][]string{
		"temperature": {"temp_humidity", "temp_pressure"},
		"humidity":    {"humidity"},
		"pressure":    {"pressure"},
		"compass":     {"compass"},
		"orientation": {"pitch", "roll", "yaw"},
		"gyroscope":   {"gyro_x", "gyro_y", "gyro_z"},
	}
	assert.Equal(t, expected, resourceGroups)
}
