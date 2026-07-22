package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"testing"
	"time"
)

func validTestConfig() Config {
	return Config{
		BaseURL:        "http://edgex-core-data.edgex-system.svc.cluster.local:59880",
		RunID:          "run-20260722",
		Devices:        1000,
		PerDeviceHz:    1,
		Duration:       time.Minute,
		Concurrency:    128,
		RequestTimeout: 5 * time.Second,
		MaxErrorRate:   0,
		MaxP95:         time.Second,
		MinRateRatio:   0.95,
		Verify:         true,
		Cleanup:        true,
	}
}

func TestConfigValidate(t *testing.T) {
	if err := validTestConfig().Validate(); err != nil {
		t.Fatalf("valid config rejected: %v", err)
	}

	tests := []struct {
		name   string
		mutate func(*Config)
		want   string
	}{
		{"base URL", func(c *Config) { c.BaseURL = "postgres://db" }, "base-url"},
		{"run ID", func(c *Config) { c.RunID = "Bad_ID" }, "run-id"},
		{"devices", func(c *Config) { c.Devices = 0 }, "devices"},
		{"frequency", func(c *Config) { c.PerDeviceHz = 0 }, "per-device-hz"},
		{"duration", func(c *Config) { c.Duration = 0 }, "duration"},
		{"concurrency", func(c *Config) { c.Concurrency = 0 }, "concurrency"},
		{"timeout", func(c *Config) { c.RequestTimeout = 0 }, "request-timeout"},
		{"error rate", func(c *Config) { c.MaxErrorRate = 1.1 }, "max-error-rate"},
		{"p95", func(c *Config) { c.MaxP95 = 0 }, "max-p95"},
		{"rate ratio", func(c *Config) { c.MinRateRatio = 0 }, "min-rate-ratio"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := validTestConfig()
			tt.mutate(&cfg)
			err := cfg.Validate()
			if err == nil || !strings.Contains(err.Error(), tt.want) {
				t.Fatalf("Validate() error = %v, want substring %q", err, tt.want)
			}
		})
	}
}

func TestPlannedEvents(t *testing.T) {
	cfg := validTestConfig()
	if got := PlannedEvents(cfg); got != 60000 {
		t.Fatalf("PlannedEvents() = %d, want 60000", got)
	}

	cfg.PerDeviceHz = 1.0 / 60.0
	if got := PlannedEvents(cfg); got != 1000 {
		t.Fatalf("low-rate PlannedEvents() = %d, want 1000", got)
	}
}

func TestPercentileUsesNearestRankWithoutMutatingInput(t *testing.T) {
	values := []time.Duration{40 * time.Millisecond, 10 * time.Millisecond, 30 * time.Millisecond, 20 * time.Millisecond}
	original := append([]time.Duration(nil), values...)

	if got := Percentile(values, 0.50); got != 20*time.Millisecond {
		t.Fatalf("p50 = %v, want 20ms", got)
	}
	if got := Percentile(values, 0.95); got != 40*time.Millisecond {
		t.Fatalf("p95 = %v, want 40ms", got)
	}
	for i := range values {
		if values[i] != original[i] {
			t.Fatalf("Percentile mutated input: got %v want %v", values, original)
		}
	}
}

func TestEvaluatePassesCompleteRun(t *testing.T) {
	cfg := validTestConfig()
	report := Report{
		Planned:     60000,
		Attempted:   60000,
		Succeeded:   60000,
		Failed:      0,
		TargetEPS:   1000,
		AchievedEPS: 990,
		ErrorRate:   0,
		Latency:     LatencyReport{P95Milliseconds: 125},
		Verification: VerificationReport{
			Enabled:   true,
			Persisted: 60000,
			Matched:   true,
		},
		Cleanup: CleanupReport{Enabled: true},
	}

	if reasons := Evaluate(cfg, report); len(reasons) != 0 {
		t.Fatalf("Evaluate() reasons = %v, want none", reasons)
	}
}

func TestEvaluateReportsEveryFailedGate(t *testing.T) {
	cfg := validTestConfig()
	report := Report{
		Planned:     60000,
		Attempted:   59999,
		Succeeded:   59000,
		Failed:      999,
		TargetEPS:   1000,
		AchievedEPS: 900,
		ErrorRate:   0.01665,
		Latency:     LatencyReport{P95Milliseconds: 1500},
		Verification: VerificationReport{
			Enabled:   true,
			Persisted: 58999,
			Matched:   false,
			Errors:    []string{"count failed"},
		},
		Cleanup: CleanupReport{Enabled: true, Errors: []string{"delete failed"}},
	}

	reasons := strings.Join(Evaluate(cfg, report), "\n")
	for _, want := range []string{
		"attempted",
		"succeeded",
		"error rate",
		"p95",
		"achieved rate",
		"readback",
		"verification errors",
		"cleanup errors",
	} {
		if !strings.Contains(reasons, want) {
			t.Errorf("reasons %q missing %q", reasons, want)
		}
	}
}

func TestBuildEventUsesEdgeXV3Contract(t *testing.T) {
	origin := int64(1784690000123456789)
	sample := Sample{
		DeviceName: "loadtest-run-20260722-0000",
		Origin:     origin,
		Value:      12.5,
	}

	request, err := BuildEvent("run-20260722", sample)
	if err != nil {
		t.Fatalf("BuildEvent() error = %v", err)
	}

	uuidV4 := regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)
	if request.APIVersion != "v3" || request.Event.APIVersion != "v3" {
		t.Fatalf("unexpected API versions: request=%q event=%q", request.APIVersion, request.Event.APIVersion)
	}
	if !uuidV4.MatchString(request.RequestID) || !uuidV4.MatchString(request.Event.ID) {
		t.Fatalf("request/event IDs are not UUID v4: %#v", request)
	}
	if request.Event.DeviceName != sample.DeviceName || request.Event.ProfileName != loadtestProfileName || request.Event.SourceName != loadtestSourceName {
		t.Fatalf("unexpected event identity: %#v", request.Event)
	}
	if request.Event.Origin != origin || request.Event.Tags[loadtestRunIDTag] != "run-20260722" {
		t.Fatalf("unexpected event origin/tags: %#v", request.Event)
	}
	if len(request.Event.Readings) != 1 {
		t.Fatalf("reading count = %d, want 1", len(request.Event.Readings))
	}
	reading := request.Event.Readings[0]
	if !uuidV4.MatchString(reading.ID) || reading.Origin != origin || reading.DeviceName != sample.DeviceName {
		t.Fatalf("unexpected reading identity: %#v", reading)
	}
	if reading.ResourceName != loadtestSourceName || reading.ProfileName != loadtestProfileName || reading.ValueType != "Float64" || reading.Value != "12.5" {
		t.Fatalf("unexpected reading payload: %#v", reading)
	}
}

func TestHTTPClientStoreUsesEdgeXRouteAndReconcilesID(t *testing.T) {
	var received AddEventRequest
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		wantPath := "/api/v3/event/core-data-loadtest/loadtest-profile-v1/loadtest-run-20260722-0007/value"
		if r.URL.Path != wantPath {
			t.Errorf("path = %q, want %q", r.URL.Path, wantPath)
		}
		if got := r.Header.Get("Content-Type"); got != "application/json" {
			t.Errorf("content-type = %q, want application/json", got)
		}
		if err := json.NewDecoder(r.Body).Decode(&received); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = fmt.Fprintf(w, `{"apiVersion":"v3","statusCode":201,"id":%q}`, received.Event.ID)
	}))
	defer server.Close()

	cfg := validTestConfig()
	cfg.BaseURL = server.URL
	client := NewHTTPClient(cfg)
	result := client.Store(context.Background(), Sample{
		DeviceName: "loadtest-run-20260722-0007",
		Origin:     time.Now().UnixNano(),
		Value:      7.25,
	})

	if result.Err != nil {
		t.Fatalf("Store() error = %v", result.Err)
	}
	if result.EventID == "" || result.EventID != received.Event.ID {
		t.Fatalf("Store() event ID = %q, request ID = %q", result.EventID, received.Event.ID)
	}
	if result.Latency <= 0 {
		t.Fatalf("Store() latency = %v, want positive", result.Latency)
	}
}

func TestHTTPClientStoreRejectsMismatchedResponseID(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"apiVersion":"v3","statusCode":201,"id":"00000000-0000-4000-8000-000000000000"}`))
	}))
	defer server.Close()

	cfg := validTestConfig()
	cfg.BaseURL = server.URL
	result := NewHTTPClient(cfg).Store(context.Background(), Sample{DeviceName: "loadtest-run-20260722-0000", Origin: 1, Value: 1})
	if result.Err == nil || !strings.Contains(result.Err.Error(), "response event ID") {
		t.Fatalf("Store() error = %v, want response ID mismatch", result.Err)
	}
}

func TestHTTPClientCountAndDeleteUseExactDeviceRoute(t *testing.T) {
	requests := make([]string, 0, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.Method+" "+r.URL.RequestURI())
		w.Header().Set("Content-Type", "application/json")
		switch r.Method {
		case http.MethodGet:
			_, _ = w.Write([]byte(`{"apiVersion":"v3","statusCode":200,"totalCount":42,"events":[]}`))
		case http.MethodDelete:
			_, _ = w.Write([]byte(`{"apiVersion":"v3","statusCode":200}`))
		default:
			w.WriteHeader(http.StatusMethodNotAllowed)
		}
	}))
	defer server.Close()

	cfg := validTestConfig()
	cfg.BaseURL = server.URL
	client := NewHTTPClient(cfg)
	deviceName := "loadtest-run-20260722-0999"

	count, err := client.Count(context.Background(), deviceName)
	if err != nil || count != 42 {
		t.Fatalf("Count() = %d, %v; want 42, nil", count, err)
	}
	if err := client.Delete(context.Background(), deviceName); err != nil {
		t.Fatalf("Delete() error = %v", err)
	}

	want := []string{
		"GET /api/v3/event/device/name/loadtest-run-20260722-0999?limit=1",
		"DELETE /api/v3/event/device/name/loadtest-run-20260722-0999",
	}
	if fmt.Sprint(requests) != fmt.Sprint(want) {
		t.Fatalf("requests = %v, want %v", requests, want)
	}
}

func TestHTTPClientBoundsErrorBody(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
		_, _ = w.Write([]byte(strings.Repeat("x", 100000)))
	}))
	defer server.Close()

	cfg := validTestConfig()
	cfg.BaseURL = server.URL
	result := NewHTTPClient(cfg).Store(context.Background(), Sample{DeviceName: "loadtest-run-20260722-0000", Origin: 1, Value: 1})
	if result.Err == nil || !strings.Contains(result.Err.Error(), "503") {
		t.Fatalf("Store() error = %v, want status 503", result.Err)
	}
	if len(result.Err.Error()) > 70000 {
		t.Fatalf("Store() error body is unbounded: %d bytes", len(result.Err.Error()))
	}
}
