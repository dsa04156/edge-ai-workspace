package driver

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gopkg.in/yaml.v3"
)

var expectedSenseHatResources = []struct {
	device      string
	profile     string
	profileFile string
	group       string
	command     string
	resources   []string
	units       []string
}{
	{"env-sensehat-temperature-01", "etri-sensehat-temperature", "etri-sensehat-temperature.yaml", "temperature", "temperature", []string{"temp_humidity", "temp_pressure"}, []string{"C", "C"}},
	{"env-sensehat-humidity-01", "etri-sensehat-humidity", "etri-sensehat-humidity.yaml", "humidity", "humidity", []string{"humidity"}, []string{"%RH"}},
	{"env-sensehat-pressure-01", "etri-sensehat-pressure", "etri-sensehat-pressure.yaml", "pressure", "pressure", []string{"pressure"}, []string{"hPa"}},
	{"imu-sensehat-compass-01", "etri-sensehat-compass", "etri-sensehat-compass.yaml", "compass", "compass", []string{"compass"}, []string{"deg"}},
	{"imu-sensehat-orientation-01", "etri-sensehat-orientation", "etri-sensehat-orientation.yaml", "orientation", "orientation", []string{"pitch", "roll", "yaw"}, []string{"deg", "deg", "deg"}},
	{"imu-sensehat-gyroscope-01", "etri-sensehat-gyroscope", "etri-sensehat-gyroscope.yaml", "gyroscope", "gyroscope", []string{"gyro_x", "gyro_y", "gyro_z"}, []string{"rad/s", "rad/s", "rad/s"}},
}

func TestResourceFilesDefineSixReadOnlySenseHatProfiles(t *testing.T) {
	for _, expected := range expectedSenseHatResources {
		t.Run(expected.device, func(t *testing.T) {
			profile := loadSenseHatYAML(t, senseHatResourcePath(t, "profiles", expected.profileFile))
			assert.Equal(t, "v2", profile["apiVersion"])
			assert.Equal(t, expected.profile, profile["name"])
			resources := requireSenseHatMapSlice(t, profile, "deviceResources")
			require.Len(t, resources, len(expected.resources))
			for index, resourceName := range expected.resources {
				assert.Equal(t, resourceName, resources[index]["name"])
				properties := requireSenseHatMap(t, resources[index], "properties")
				assert.Equal(t, "Float64", properties["valueType"])
				assert.Equal(t, "R", properties["readWrite"])
				assert.Equal(t, expected.units[index], properties["units"])
			}
			commands := requireSenseHatMapSlice(t, profile, "deviceCommands")
			require.Len(t, commands, 1)
			assert.Equal(t, expected.command, commands[0]["name"])
			assert.Equal(t, "R", commands[0]["readWrite"])
			operations := requireSenseHatMapSlice(t, commands[0], "resourceOperations")
			require.Len(t, operations, len(expected.resources))
			for index, resourceName := range expected.resources {
				assert.Equal(t, resourceName, operations[index]["deviceResource"])
			}
		})
	}
}

func TestResourceFilesDefineExactSenseHatVirtualDevices(t *testing.T) {
	devices := loadSenseHatYAML(t, senseHatResourcePath(t, "devices", "sensehat-virtual-devices.yaml"))
	deviceList := requireSenseHatMapSlice(t, devices, "deviceList")
	require.Len(t, deviceList, 6)
	byName := make(map[string]map[string]any, 6)
	for _, device := range deviceList {
		byName[requireSenseHatString(t, device, "name")] = device
	}
	for _, expected := range expectedSenseHatResources {
		device := byName[expected.device]
		require.NotNil(t, device)
		assert.Equal(t, expected.profile, device["profileName"])
		_, hasAutoEvents := device["autoEvents"]
		assert.False(t, hasAutoEvents)
		protocols := requireSenseHatMap(t, device, "protocols")
		i2c := requireSenseHatMap(t, protocols, "i2c")
		assert.Equal(t, "/dev/i2c-1", i2c["Bus"])
		assert.Equal(t, "sensehat-001", i2c["DeviceID"])
		assert.Equal(t, expected.group, i2c["ResourceGroup"])
		tags := requireSenseHatMap(t, device, "tags")
		assert.Equal(t, "sensehat-001", tags["physicalDeviceId"])
		assert.Equal(t, "etri-dev0003-raspi5", tags["nodeName"])
	}
	_, err := os.Stat(senseHatResourcePath(t, "devices", "sensehat-001.yaml"))
	assert.ErrorIs(t, err, os.ErrNotExist)
}

func TestResourceFilesEnableSenseHatAsyncSDK(t *testing.T) {
	configuration := loadSenseHatYAML(t, senseHatResourcePath(t, "configuration.yaml"))
	service := requireSenseHatMap(t, configuration, "Service")
	assert.Equal(t, 59911, service["Port"])
	messageBus := requireSenseHatMap(t, configuration, "MessageBus")
	assert.Equal(t, "edgex-messagebus", messageBus["Host"])
	assert.Equal(t, "device-sensehat-raspi", requireSenseHatMap(t, messageBus, "Optional")["ClientId"])
	device := requireSenseHatMap(t, configuration, "Device")
	assert.Equal(t, 32, device["AsyncBufferSize"])
	assert.Equal(t, false, requireSenseHatMap(t, device, "Discovery")["Enabled"])
}

func senseHatResourcePath(t *testing.T, elements ...string) string {
	t.Helper()
	_, sourceFile, _, ok := runtime.Caller(0)
	require.True(t, ok)
	pathElements := append([]string{filepath.Dir(sourceFile), "..", "..", "res"}, elements...)
	return filepath.Clean(filepath.Join(pathElements...))
}

func loadSenseHatYAML(t *testing.T, path string) map[string]any {
	t.Helper()
	contents, err := os.ReadFile(path)
	require.NoError(t, err)
	var result map[string]any
	require.NoError(t, yaml.Unmarshal(contents, &result))
	return result
}

func requireSenseHatMap(t *testing.T, parent map[string]any, key string) map[string]any {
	t.Helper()
	value, ok := parent[key].(map[string]any)
	require.Truef(t, ok, "%s must be a map, got %T", key, parent[key])
	return value
}

func requireSenseHatMapSlice(t *testing.T, parent map[string]any, key string) []map[string]any {
	t.Helper()
	raw, ok := parent[key].([]any)
	require.Truef(t, ok, "%s must be a list, got %T", key, parent[key])
	result := make([]map[string]any, len(raw))
	for index, value := range raw {
		result[index], ok = value.(map[string]any)
		require.Truef(t, ok, "%s[%d] must be a map, got %T", key, index, value)
	}
	return result
}

func requireSenseHatString(t *testing.T, parent map[string]any, key string) string {
	t.Helper()
	value, ok := parent[key].(string)
	require.Truef(t, ok, "%s must be a string, got %T", key, parent[key])
	return value
}
