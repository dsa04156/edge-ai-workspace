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
		"runStatusHeartbeatReporter",
		"status.BuildHeartbeatSummary",
		"status.DMIReporter{}",
		"DEVICE_STATUS_HEARTBEAT_SECONDS",
	} {
		if !strings.Contains(text, marker) {
			t.Fatalf("devicestatus.go must run low-frequency DeviceStatus heartbeat reporter; missing marker %q", marker)
		}
	}
	if strings.Contains(text, "if !deviceStates.ReportToCloud {\n\t\treturn\n\t}") {
		t.Fatalf("DeviceStatus heartbeat must not be disabled by spec.status.reportToCloud=false")
	}
	if strings.Contains(text, "if !envBool(\"DEVICE_STATES_REPORT_ENABLED\", false) {\n\t\treturn") {
		t.Fatalf("DeviceStatus heartbeat must not be disabled by the legacy DeviceStates env gate")
	}
}
