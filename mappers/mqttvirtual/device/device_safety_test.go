package device

import (
	"os"
	"strings"
	"testing"
)

func readDeviceSource(t *testing.T) string {
	t.Helper()
	content, err := os.ReadFile("device.go")
	if err != nil {
		t.Fatal(err)
	}
	return string(content)
}

func TestDataHandlerChecksUnmarshalBeforeVisitorAccess(t *testing.T) {
	text := readDeviceSource(t)
	bad := "json.Unmarshal(twin.Property.Visitors, &visitorConfig)\n\t\tvisitorConfig.VisitorConfigData.DataType"
	if strings.Contains(text, bad) {
		t.Fatalf("visitorConfig must not be accessed before json.Unmarshal error is checked")
	}
}

func TestUpdateDevTwinsDoesNotCallUpdateDevWhileLocked(t *testing.T) {
	text := readDeviceSource(t)
	bad := "func (d *DevPanel) UpdateDevTwins(deviceID string, twins []common.Twin) error {\n\td.serviceMutex.Lock()"
	if strings.Contains(text, bad) && strings.Contains(text, "\td.UpdateDev(&model, &dev.Instance)") {
		t.Fatalf("UpdateDevTwins must not call UpdateDev while serviceMutex is held")
	}
}

func TestDealDeviceTwinGetUsesActualTwinPropertyName(t *testing.T) {
	text := readDeviceSource(t)
	if strings.Contains(text, "PropertyName: twinName,") {
		t.Fatalf("DealDeviceTwinGet response must use twin.PropertyName, not the request filter twinName")
	}
	if !strings.Contains(text, "PropertyName: twin.PropertyName,") {
		t.Fatalf("DealDeviceTwinGet should set each response PropertyName from twin.PropertyName")
	}
}

func TestDeviceStatusAllowlistExcludesRawTelemetry(t *testing.T) {
	rawNames := []string{"raw", "value", "temperature", "humidity", "current", "voltage", "x", "y", "z", "acceleration", "light", "magnetic", "lastSeen", "last_seen", "telemetryFresh", "telemetry_fresh", "source"}
	for _, name := range rawNames {
		if _, ok := deviceStatusPropertyAllowlist[name]; ok {
			t.Fatalf("raw telemetry property %q must not be reported as DeviceStatus/DeviceTwin", name)
		}
	}
	stateNames := []string{"health", "severity", "alarm_latched", "command_state", "temperature_status", "humidity_status", "vibration_status", "mapperLastSeen", "controlLastSeen", "statusLastSeen", "statusSource"}
	for _, name := range stateNames {
		if _, ok := deviceStatusPropertyAllowlist[name]; !ok {
			t.Fatalf("operational state property %q should remain allowed", name)
		}
	}
}

func TestDevicePanelSafetyMarkers(t *testing.T) {
	text := readDeviceSource(t)
	markers := []string{
		"sync.RWMutex",
		"func (d *DevPanel) snapshotDevices()",
		"func stopCustomizedDevice",
		"dev == nil || dev.CustomizedClient == nil",
		"twin == nil || twin.Property == nil",
		"timer.Stop()",
		"for len(dev.CustomizedClient.Events) > 0",
		"device=%s property=%s",
	}
	for _, marker := range markers {
		if !strings.Contains(text, marker) {
			t.Fatalf("device.go missing safety marker %q", marker)
		}
	}
}
