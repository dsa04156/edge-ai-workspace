package status

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestBuildDeviceStatusStatusPatchUsesOnlySummaryTwins(t *testing.T) {
	payload, err := buildDeviceStatusStatusPatch(map[string]string{
		"mapperLastSeen":     "2026-05-26T09:40:00Z",
		"statusLastSeen":     "2026-05-26T09:40:00Z",
		"statusSource":       "mapper-framework",
		"last_error_code":    "",
		"last_error_message": "",
	})
	if err != nil {
		t.Fatalf("build patch failed: %v", err)
	}

	var patch deviceStatusPatch
	if err := json.Unmarshal(payload, &patch); err != nil {
		t.Fatalf("unmarshal patch failed: %v", err)
	}
	if !patch.Status.ReportToCloud {
		t.Fatalf("reportToCloud should be true in status patch")
	}
	if len(patch.Status.Twins) != 5 {
		t.Fatalf("expected 5 status twins, got %d: %s", len(patch.Status.Twins), payload)
	}
	for _, twin := range patch.Status.Twins {
		if !IsSummaryField(twin.PropertyName) {
			t.Fatalf("unexpected non-summary twin %q", twin.PropertyName)
		}
		if twin.PropertyName == "health" || twin.PropertyName == "online" || twin.PropertyName == "severity" {
			t.Fatalf("derived health/online/severity twin should not be patched: %q", twin.PropertyName)
		}
		if twin.Reported.Metadata["type"] != "string" {
			t.Fatalf("reported metadata type = %q, want string", twin.Reported.Metadata["type"])
		}
		if twin.Reported.Metadata["timestamp"] == "" {
			t.Fatalf("reported metadata timestamp should be set")
		}
	}
}

func TestBuildDeviceStatusStatusPatchRejectsRawTelemetry(t *testing.T) {
	_, err := buildDeviceStatusStatusPatch(map[string]string{"value": "25"})
	if err == nil {
		t.Fatalf("expected raw telemetry field to be rejected")
	}
}

func TestGetCurrentKubernetesStatusValuesKeepsOnlyAllowedSummaryFields(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("method = %s, want GET", r.Method)
		}
		_, _ = w.Write([]byte(`{
			"status": {
				"twins": [
					{"propertyName":"mapperLastSeen","reported":{"value":"2026-05-26T09:40:00Z"}},
					{"propertyName":"value","reported":{"value":"25"}},
					{"propertyName":"statusSource","reported":{"value":"mapper-framework"}}
				]
			}
		}`))
	}))
	defer server.Close()

	values, err := getCurrentKubernetesStatusValues(context.Background(), server.Client(), "token", server.URL)
	if err != nil {
		t.Fatalf("get current status failed: %v", err)
	}
	if values["mapperLastSeen"] != "2026-05-26T09:40:00Z" {
		t.Fatalf("mapperLastSeen not preserved: %+v", values)
	}
	if values["statusSource"] != "mapper-framework" {
		t.Fatalf("statusSource not preserved: %+v", values)
	}
	if _, ok := values["value"]; ok {
		t.Fatalf("raw telemetry field should not be preserved: %+v", values)
	}
}

func TestKubernetesDeviceStatusEndpointUsesExplicitAPIServer(t *testing.T) {
	endpoint := kubernetesDeviceStatusEndpoint(Summary{
		DeviceName:      "env-arduino-light-01",
		DeviceNamespace: "default",
	}, "https://192.168.0.56:6443")
	want := "https://192.168.0.56:6443/apis/devices.kubeedge.io/v1beta1/namespaces/default/devices/env-arduino-light-01/status"
	if endpoint != want {
		t.Fatalf("endpoint = %q, want %q", endpoint, want)
	}
}
