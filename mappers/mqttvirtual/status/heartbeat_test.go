package status

import (
	"testing"
	"time"
)

func TestBuildHeartbeatSummaryReportsOnlineMapperStatus(t *testing.T) {
	now := time.Date(2026, 5, 21, 13, 30, 0, 0, time.UTC)

	summary := BuildHeartbeatSummary("env-arduino-temperature-01", "default", now, "online", nil)

	if summary.DeviceName != "env-arduino-temperature-01" || summary.DeviceNamespace != "default" {
		t.Fatalf("unexpected heartbeat identity: %+v", summary)
	}
	want := map[string]string{
		"mapperLastSeen":     now.Format(time.RFC3339),
		"statusLastSeen":     now.Format(time.RFC3339),
		"statusSource":       "mapper-framework",
		"last_error_code":    "",
		"last_error_message": "",
	}
	if len(summary.Values) != len(want) {
		t.Fatalf("heartbeat must contain exactly the allowed fields, got %+v", summary.Values)
	}
	for key, value := range want {
		if summary.Values[key] != value {
			t.Fatalf("heartbeat field %s = %q, want %q; summary=%+v", key, summary.Values[key], value, summary.Values)
		}
	}
	if _, ok := summary.Values["temperature"]; ok {
		t.Fatalf("heartbeat must not include raw telemetry fields: %+v", summary.Values)
	}
}

func TestBuildHeartbeatSummaryReportsFailureStatus(t *testing.T) {
	now := time.Date(2026, 5, 21, 13, 31, 0, 0, time.UTC)

	summary := BuildHeartbeatSummary("env-arduino-temperature-01", "default", now, "disconnected", errString("mqtt connection lost"))

	want := map[string]string{
		"mapperLastSeen":     now.Format(time.RFC3339),
		"statusLastSeen":     now.Format(time.RFC3339),
		"statusSource":       "mapper-framework",
		"last_error_code":    "mapper_status_error",
		"last_error_message": "mqtt connection lost",
	}
	if len(summary.Values) != len(want) {
		t.Fatalf("failure heartbeat must contain exactly the allowed fields, got %+v", summary.Values)
	}
	for key, value := range want {
		if summary.Values[key] != value {
			t.Fatalf("failure heartbeat field %s = %q, want %q; summary=%+v", key, summary.Values[key], value, summary.Values)
		}
	}
}

func TestBuildHeartbeatSummaryReportsTelemetryStaleAsDegraded(t *testing.T) {
	now := time.Date(2026, 5, 21, 13, 32, 0, 0, time.UTC)

	summary := BuildHeartbeatSummary("env-arduino-temperature-01", "default", now, "telemetry_stale", nil)

	want := map[string]string{
		"mapperLastSeen":     now.Format(time.RFC3339),
		"statusLastSeen":     now.Format(time.RFC3339),
		"statusSource":       "mapper-framework",
		"last_error_code":    "telemetry_input_stale",
		"last_error_message": "telemetry input is stale",
	}
	if len(summary.Values) != len(want) {
		t.Fatalf("telemetry stale heartbeat must contain exactly the allowed fields, got %+v", summary.Values)
	}
	for key, value := range want {
		if summary.Values[key] != value {
			t.Fatalf("telemetry stale heartbeat field %s = %q, want %q; summary=%+v", key, summary.Values[key], value, summary.Values)
		}
	}
	if _, ok := summary.Values["temperature"]; ok {
		t.Fatalf("telemetry stale heartbeat must not include raw telemetry fields: %+v", summary.Values)
	}
}

func TestBuildHeartbeatSummaryReportsTelemetryMissingAsDegraded(t *testing.T) {
	now := time.Date(2026, 5, 21, 13, 33, 0, 0, time.UTC)

	summary := BuildHeartbeatSummary("env-arduino-temperature-01", "default", now, "telemetry_missing", nil)

	for _, key := range []string{"health", "severity", "online"} {
		if _, ok := summary.Values[key]; ok {
			t.Fatalf("heartbeat must not include derived field %s: %+v", key, summary.Values)
		}
	}
	if summary.Values["last_error_code"] != "telemetry_input_missing" {
		t.Fatalf("last_error_code=%q, want telemetry_input_missing", summary.Values["last_error_code"])
	}
}

type errString string

func (e errString) Error() string { return string(e) }
