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

var expectedVirtualDevices = []struct {
	name        string
	profile     string
	profileFile string
	resource    string
	command     string
}{
	{"virtual-temperature-001", "etri-arduino-temperature", "etri-arduino-temperature.yaml", "temperature_raw", "temperature"},
	{"virtual-light-001", "etri-arduino-light", "etri-arduino-light.yaml", "light_raw", "light"},
	{"virtual-magnetic-001", "etri-arduino-magnetic", "etri-arduino-magnetic.yaml", "magnetic_raw", "magnetic"},
	{"virtual-acceleration-x-001", "etri-arduino-acceleration-x", "etri-arduino-acceleration-x.yaml", "acceleration_x_raw", "acceleration_x"},
	{"virtual-acceleration-y-001", "etri-arduino-acceleration-y", "etri-arduino-acceleration-y.yaml", "acceleration_y_raw", "acceleration_y"},
	{"virtual-acceleration-z-001", "etri-arduino-acceleration-z", "etri-arduino-acceleration-z.yaml", "acceleration_z_raw", "acceleration_z"},
}

func TestResourceFilesDefineSixReadOnlyVirtualProfiles(t *testing.T) {
	for _, expected := range expectedVirtualDevices {
		t.Run(expected.name, func(t *testing.T) {
			profile := loadYAMLMap(t, resourcePath(t, "profiles", expected.profileFile))
			assert.Equal(t, "v2", profile["apiVersion"])
			assert.Equal(t, expected.profile, profile["name"])

			resources := requireMapSlice(t, profile, "deviceResources")
			require.Len(t, resources, 1)
			assert.Equal(t, expected.resource, resources[0]["name"])
			properties := requireMap(t, resources[0], "properties")
			assert.Equal(t, "Int32", properties["valueType"])
			assert.Equal(t, "R", properties["readWrite"])
			assert.Equal(t, "raw", properties["units"])

			commands := requireMapSlice(t, profile, "deviceCommands")
			require.Len(t, commands, 1)
			assert.Equal(t, expected.command, commands[0]["name"])
			assert.Equal(t, "R", commands[0]["readWrite"])
			operations := requireMapSlice(t, commands[0], "resourceOperations")
			require.Len(t, operations, 1)
			assert.Equal(t, expected.resource, operations[0]["deviceResource"])
		})
	}

	_, err := os.Stat(resourcePath(t, "profiles", "etri-arduino-serial.yaml"))
	assert.ErrorIs(t, err, os.ErrNotExist)
}

func TestResourceFilesDefineExactVirtualDevices(t *testing.T) {
	devices := loadYAMLMap(t, resourcePath(t, "devices", "arduino-virtual-devices.yaml"))
	deviceList := requireMapSlice(t, devices, "deviceList")
	require.Len(t, deviceList, len(expectedVirtualDevices))

	byName := make(map[string]map[string]any, len(deviceList))
	for _, device := range deviceList {
		byName[requireString(t, device, "name")] = device
	}
	for _, expected := range expectedVirtualDevices {
		device := byName[expected.name]
		require.NotNil(t, device)
		assert.Equal(t, expected.profile, device["profileName"])
		_, hasAutoEvents := device["autoEvents"]
		assert.False(t, hasAutoEvents)

		protocols := requireMap(t, device, "protocols")
		serial := requireMap(t, protocols, "serial")
		assert.Equal(t, "/dev/arduino-001", serial["Port"])
		assert.Equal(t, "115200", serial["BaudRate"])
		assert.Equal(t, "arduino-001", serial["DeviceID"])
		assert.Equal(t, expected.resource, serial["ResourceName"])
		assert.Equal(t, "on-demand-read", serial["RecoveryStrategy"])

		tags := requireMap(t, device, "tags")
		assert.Equal(t, "arduino-001", tags["physicalDeviceId"])
		assert.Equal(t, "etri-dev0001-jetorn", tags["nodeName"])
	}

	_, err := os.Stat(resourcePath(t, "devices", "arduino-001.yaml"))
	assert.ErrorIs(t, err, os.ErrNotExist)
}

func TestResourceFilesEnableAsyncSDKWithoutDiscovery(t *testing.T) {
	configuration := loadYAMLMap(t, resourcePath(t, "configuration.yaml"))
	service := requireMap(t, configuration, "Service")
	assert.Equal(t, 59910, service["Port"])

	messageBus := requireMap(t, configuration, "MessageBus")
	assert.Equal(t, "edgex-messagebus", messageBus["Host"])
	optional := requireMap(t, messageBus, "Optional")
	assert.Equal(t, "device-serial-jetson", optional["ClientId"])
	clients := requireMap(t, configuration, "Clients")
	coreMetadata := requireMap(t, clients, "core-metadata")
	assert.Equal(t, "edgex-core-metadata", coreMetadata["Host"])

	device := requireMap(t, configuration, "Device")
	assert.Equal(t, 16, device["AsyncBufferSize"])
	assert.Equal(t, "/res/profiles", device["ProfilesDir"])
	assert.Equal(t, "/res/devices", device["DevicesDir"])
	discovery := requireMap(t, device, "Discovery")
	assert.Equal(t, false, discovery["Enabled"])
}

func resourcePath(t *testing.T, elements ...string) string {
	t.Helper()
	_, sourceFile, _, ok := runtime.Caller(0)
	require.True(t, ok)
	pathElements := append([]string{filepath.Dir(sourceFile), "..", "..", "res"}, elements...)
	return filepath.Clean(filepath.Join(pathElements...))
}

func loadYAMLMap(t *testing.T, path string) map[string]any {
	t.Helper()
	contents, err := os.ReadFile(path)
	require.NoError(t, err)
	var result map[string]any
	require.NoError(t, yaml.Unmarshal(contents, &result))
	return result
}

func requireMap(t *testing.T, parent map[string]any, key string) map[string]any {
	t.Helper()
	value, ok := parent[key].(map[string]any)
	require.Truef(t, ok, "%s must be a map, got %T", key, parent[key])
	return value
}

func requireMapSlice(t *testing.T, parent map[string]any, key string) []map[string]any {
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

func requireString(t *testing.T, parent map[string]any, key string) string {
	t.Helper()
	value, ok := parent[key].(string)
	require.Truef(t, ok, "%s must be a string, got %T", key, parent[key])
	return value
}
