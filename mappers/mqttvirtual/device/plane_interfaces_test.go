package device

import (
	"testing"

	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mqttvirtual/status"
)

func TestStatusReporterAcceptsOnlySummaryFields(t *testing.T) {
	allowed := []string{"health", "mapperLastSeen", "controlLastSeen", "statusLastSeen", "statusSource", "severity", "command_state", "online", "offline", "control_response"}
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

func TestMapperFrameworkMainPathExcludesRawTelemetryProperties(t *testing.T) {
	raw := []string{"temperature", "humidity", "vibration", "acceleration_x", "acceleration_y", "acceleration_z", "current", "voltage", "waveform"}
	for _, field := range raw {
		if shouldProcessMapperControlStatusProperty(&common.Twin{PropertyName: field, Property: &common.DeviceProperty{}}) {
			t.Fatalf("raw telemetry field %q must be excluded from MapperFramework main path", field)
		}
	}

	summary := []string{"health", "severity", "command_state", "control_response", "statusSource"}
	for _, field := range summary {
		if !shouldProcessMapperControlStatusProperty(&common.Twin{PropertyName: field, Property: &common.DeviceProperty{}}) {
			t.Fatalf("summary field %q should remain in MapperFramework control/status path", field)
		}
	}
}
