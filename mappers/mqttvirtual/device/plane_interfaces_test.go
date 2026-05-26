package device

import (
	"testing"

	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mqttvirtual/status"
)

func TestStatusReporterAcceptsOnlySummaryFields(t *testing.T) {
	allowed := []string{"mapperLastSeen", "controlLastSeen", "statusLastSeen", "statusSource", "command_state", "control_response", "last_error_code", "last_error_message"}
	for _, field := range allowed {
		if !status.IsSummaryField(field) {
			t.Fatalf("summary field %q should be allowed for DeviceStatus", field)
		}
	}

	rejected := []string{"temperature", "humidity", "vibration", "acceleration_x", "acceleration_y", "acceleration_z", "current", "voltage", "raw", "value", "x", "y", "z", "waveform", "raw_samples", "lastSeen", "last_seen", "telemetryFresh", "telemetry_fresh", "source"}
	for _, field := range rejected {
		if status.IsSummaryField(field) {
			t.Fatalf("raw/deprecated field %q must not be accepted as DeviceStatus summary", field)
		}
		_, err := (&TwinData{Name: field}).BuildStatusSummary()
		if err == nil {
			t.Fatalf("raw/deprecated field %q must not build a DeviceStatus summary", field)
		}
	}
}

func TestDefaultStatusReporterImplementsStatusReporter(t *testing.T) {
	var _ status.Reporter = status.DMIReporter{}
}

func TestMapperFrameworkDataPathAllowsRawTelemetryWhileDeviceStatusRejectsIt(t *testing.T) {
	raw := []string{"temperature", "humidity", "vibration", "acceleration_x", "acceleration_y", "acceleration_z", "current", "voltage", "waveform"}
	for _, field := range raw {
		if shouldReportAsTwinProperty(&common.Twin{PropertyName: field, Property: &common.DeviceProperty{ReportToCloud: true}}) {
			t.Fatalf("raw telemetry field %q must not be reported through DeviceStatus", field)
		}
	}

	summary := []string{"mapperLastSeen", "statusLastSeen", "statusSource", "last_error_code", "last_error_message", "command_state", "control_response"}
	for _, field := range summary {
		if !shouldReportAsTwinProperty(&common.Twin{PropertyName: field, Property: &common.DeviceProperty{ReportToCloud: true}}) {
			t.Fatalf("summary field %q should remain eligible for DeviceStatus", field)
		}
	}
}
