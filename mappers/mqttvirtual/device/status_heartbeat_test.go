package device

import (
	"os"
	"strings"
	"testing"
)

func TestDeviceStatesReportsLowFrequencyDeviceStatusHeartbeat(t *testing.T) {
	content, err := os.ReadFile("devicestatus.go")
	if err != nil {
		t.Fatal(err)
	}
	text := string(content)
	for _, marker := range []string{
		"status.BuildHeartbeatSummary",
		"status.DMIReporter{}",
		"DEVICE_STATES_REPORT_ENABLED",
		"deviceStates.PushStatesToEdgeCore()",
	} {
		if !strings.Contains(text, marker) {
			t.Fatalf("devicestatus.go must report low-frequency DeviceStatus heartbeat; missing marker %q", marker)
		}
	}
	if strings.Contains(text, "if !envBool(\"DEVICE_STATES_REPORT_ENABLED\", false) {\n\t\tklog.V(2)") {
		t.Fatalf("DeviceStatus heartbeat must not be disabled by the legacy DeviceStates env gate")
	}
}
