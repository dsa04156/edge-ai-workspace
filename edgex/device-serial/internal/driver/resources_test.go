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

func TestResourceFilesDefineReadOnlyArduinoProfile(t *testing.T) {
	profile := loadYAMLMap(t, resourcePath(t, "profiles", "etri-arduino-serial.yaml"))

	assert.Equal(t, "v2", profile["apiVersion"])
	assert.Equal(t, "etri-arduino-serial", profile["name"])

	resources := requireMapSlice(t, profile, "deviceResources")
	require.Len(t, resources, 6)
	expectedResources := map[string]struct{}{
		"temperature_raw":    {},
		"light_raw":          {},
		"magnetic_raw":       {},
		"acceleration_x_raw": {},
		"acceleration_y_raw": {},
		"acceleration_z_raw": {},
	}
	for _, resource := range resources {
		name := requireString(t, resource, "name")
		_, expected := expectedResources[name]
		assert.Truef(t, expected, "unexpected resource %q", name)
		delete(expectedResources, name)
		properties := requireMap(t, resource, "properties")
		assert.Equal(t, "Int32", properties["valueType"])
		assert.Equal(t, "R", properties["readWrite"])
	}
	assert.Empty(t, expectedResources)

	commands := requireMapSlice(t, profile, "deviceCommands")
	require.Len(t, commands, 4)
	expectedCommands := map[string][]string{
		"temperature":  {"temperature_raw"},
		"light":        {"light_raw"},
		"magnetic":     {"magnetic_raw"},
		"acceleration": {"acceleration_x_raw", "acceleration_y_raw", "acceleration_z_raw"},
	}
	for _, command := range commands {
		name := requireString(t, command, "name")
		assert.Equal(t, "R", command["readWrite"])
		operations := requireMapSlice(t, command, "resourceOperations")
		operationNames := make([]string, 0, len(operations))
		for _, operation := range operations {
			operationNames = append(operationNames, requireString(t, operation, "deviceResource"))
		}
		assert.Equal(t, expectedCommands[name], operationNames)
		delete(expectedCommands, name)
	}
	assert.Empty(t, expectedCommands)
}

func TestResourceFilesDefineExactArduinoDevice(t *testing.T) {
	devices := loadYAMLMap(t, resourcePath(t, "devices", "arduino-001.yaml"))
	deviceList := requireMapSlice(t, devices, "deviceList")
	require.Len(t, deviceList, 1)
	device := deviceList[0]

	assert.Equal(t, "arduino-001", device["name"])
	assert.Equal(t, "etri-arduino-serial", device["profileName"])
	_, hasAutoEvents := device["autoEvents"]
	assert.False(t, hasAutoEvents)

	protocols := requireMap(t, device, "protocols")
	serial := requireMap(t, protocols, "serial")
	assert.Equal(t, "/dev/arduino-001", serial["Port"])
	assert.Equal(t, "115200", serial["BaudRate"])
	assert.Equal(t, "arduino-001", serial["DeviceID"])
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
