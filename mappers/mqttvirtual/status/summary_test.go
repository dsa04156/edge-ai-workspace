package status

import "testing"

func TestSummaryRejectsRawTelemetryFields(t *testing.T) {
	for _, field := range []string{"temperature", "humidity", "vibration", "acceleration_x", "acceleration_y", "acceleration_z", "current", "voltage", "raw", "value", "x", "y", "z", "waveform", "raw_samples"} {
		if IsSummaryField(field) {
			t.Fatalf("raw telemetry field %q must not be allowed in DeviceStatus summary", field)
		}
	}
}

func TestSummaryAllowsControlStatusFields(t *testing.T) {
	for _, field := range []string{"health", "mapperLastSeen", "controlLastSeen", "statusLastSeen", "statusSource", "severity", "command_state", "online", "offline", "control_response"} {
		if !IsSummaryField(field) {
			t.Fatalf("summary field %q should be allowed", field)
		}
	}
}

func TestDeprecatedSummaryFieldsAreNotAllowed(t *testing.T) {
	for _, field := range []string{"lastSeen", "last_seen", "telemetryFresh", "telemetry_fresh", "source"} {
		if IsSummaryField(field) {
			t.Fatalf("deprecated field %q must not be in DeviceStatus allowlist", field)
		}
		if !IsDeprecatedSummaryField(field) {
			t.Fatalf("deprecated field %q should be tracked as deprecated", field)
		}
	}
}

func TestReporterInterfaceIsSummaryOnly(t *testing.T) {
	var _ Reporter = DMIReporter{}
}
