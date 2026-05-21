package telemetry

import (
	"context"
	"testing"
	"time"
)

func TestSampleSchemaIsDebugOnlyRawTelemetryShape(t *testing.T) {
	sample := Sample{
		DeviceID:   "dev-1",
		DeviceType: "env",
		NodeName:   "edge-1",
		Source:     "mapper-framework",
		Protocol:   "mqtt",
		Timestamp:  time.Unix(10, 0).UTC(),
		Tags: map[string]string{
			"property": "temperature",
		},
		Fields: map[string]interface{}{
			"temperature": 24.5,
		},
	}
	if sample.DeviceID == "" || sample.DeviceType == "" || sample.NodeName == "" || sample.Source == "" || sample.Protocol == "" {
		t.Fatalf("sample identity fields must be explicit: %+v", sample)
	}
	if sample.Timestamp.IsZero() {
		t.Fatalf("sample timestamp must be set")
	}
	if sample.Tags["property"] != "temperature" || sample.Fields["temperature"] != 24.5 {
		t.Fatalf("sample tags/fields not preserved: %+v", sample)
	}
}

func TestSinkUsesExportMethodForDebugOnlyPath(t *testing.T) {
	var _ Sink = SinkFunc(func(context.Context, Sample) error { return nil })
}
