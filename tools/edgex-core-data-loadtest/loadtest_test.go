package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"net/http/httptest"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"
)

func validTestConfig() Config {
	return Config{
		BaseURL:                "http://edgex-core-data.edgex-system.svc.cluster.local:59880",
		RunID:                  "run-20260722",
		Devices:                1000,
		PerDeviceHz:            1,
		Duration:               time.Minute,
		Concurrency:            128,
		MaintenanceConcurrency: 8,
		RequestTimeout:         5 * time.Second,
		MaxErrorRate:           0,
		MaxP95:                 time.Second,
		MinRateRatio:           0.95,
		Verify:                 true,
		Cleanup:                true,
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
		{"maintenance concurrency", func(c *Config) { c.MaintenanceConcurrency = 0 }, "maintenance-concurrency"},
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
	deleted := false
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests = append(requests, r.Method+" "+r.URL.RequestURI())
		w.Header().Set("Content-Type", "application/json")
		switch r.Method {
		case http.MethodGet:
			count := 42
			if deleted {
				count = 0
			}
			_, _ = fmt.Fprintf(w, `{"apiVersion":"v3","statusCode":200,"count":%d}`, count)
		case http.MethodDelete:
			deleted = true
			w.WriteHeader(http.StatusAccepted)
			_, _ = w.Write([]byte(`{"apiVersion":"v3","statusCode":202}`))
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
		"GET /api/v3/event/count/device/name/loadtest-run-20260722-0999",
		"DELETE /api/v3/event/device/name/loadtest-run-20260722-0999",
		"GET /api/v3/event/count/device/name/loadtest-run-20260722-0999",
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

type fakeEventClient struct {
	mu             sync.Mutex
	counts         map[string]int64
	storeCalls     []Sample
	deleted        map[string]bool
	storeDelay     time.Duration
	failStore      func(Sample) error
	failCount      map[string]error
	failDelete     map[string]error
	active         int
	maxActive      int
	countOverrides map[string]int64
}

func newFakeEventClient() *fakeEventClient {
	return &fakeEventClient{
		counts:         make(map[string]int64),
		deleted:        make(map[string]bool),
		failCount:      make(map[string]error),
		failDelete:     make(map[string]error),
		countOverrides: make(map[string]int64),
	}
}

func (f *fakeEventClient) Store(ctx context.Context, sample Sample) StoreResult {
	started := time.Now()
	f.mu.Lock()
	f.active++
	if f.active > f.maxActive {
		f.maxActive = f.active
	}
	f.storeCalls = append(f.storeCalls, sample)
	f.mu.Unlock()

	select {
	case <-ctx.Done():
		f.mu.Lock()
		f.active--
		f.mu.Unlock()
		return StoreResult{Latency: time.Since(started), Err: ctx.Err()}
	case <-time.After(f.storeDelay):
	}

	f.mu.Lock()
	defer f.mu.Unlock()
	f.active--
	if f.failStore != nil {
		if err := f.failStore(sample); err != nil {
			return StoreResult{Latency: time.Since(started), Err: err}
		}
	}
	f.counts[sample.DeviceName]++
	return StoreResult{EventID: fmt.Sprintf("event-%d", sample.Sequence), Latency: time.Since(started)}
}

func (f *fakeEventClient) Count(_ context.Context, deviceName string) (int64, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.failCount[deviceName]; err != nil {
		return 0, err
	}
	if count, ok := f.countOverrides[deviceName]; ok {
		return count, nil
	}
	return f.counts[deviceName], nil
}

func (f *fakeEventClient) Delete(_ context.Context, deviceName string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if err := f.failDelete[deviceName]; err != nil {
		return err
	}
	f.deleted[deviceName] = true
	return nil
}

func fastRunnerConfig() Config {
	cfg := validTestConfig()
	cfg.Devices = 4
	cfg.PerDeviceHz = 1000
	cfg.Duration = 4 * time.Millisecond
	cfg.Concurrency = 3
	cfg.RequestTimeout = time.Second
	cfg.MaxP95 = time.Second
	cfg.MinRateRatio = 0.01
	return cfg
}

func TestRunAttemptsExactPlanAndUsesRoundRobinDevices(t *testing.T) {
	cfg := fastRunnerConfig()
	client := newFakeEventClient()

	report := Run(context.Background(), cfg, client)

	if report.Planned != 16 || report.Attempted != 16 || report.Succeeded != 16 || report.Failed != 0 {
		t.Fatalf("unexpected counters: %#v", report)
	}
	if report.Verification.Persisted != 16 || !report.Verification.Matched || report.Verification.CheckedDevices != 4 {
		t.Fatalf("unexpected verification: %#v", report.Verification)
	}
	if report.Cleanup.Deleted != 4 || len(client.deleted) != 4 {
		t.Fatalf("unexpected cleanup: report=%#v deleted=%v", report.Cleanup, client.deleted)
	}
	for index := 0; index < cfg.Devices; index++ {
		deviceName := DeviceName(cfg.RunID, index)
		if got := client.counts[deviceName]; got != 4 {
			t.Errorf("device %s count = %d, want 4", deviceName, got)
		}
	}
	if !report.Pass || len(report.Reasons) != 0 {
		t.Fatalf("report failed: %v", report.Reasons)
	}
}

func TestRunRespectsConcurrencyLimit(t *testing.T) {
	cfg := fastRunnerConfig()
	cfg.Duration = 10 * time.Millisecond
	client := newFakeEventClient()
	client.storeDelay = 2 * time.Millisecond

	_ = Run(context.Background(), cfg, client)

	if client.maxActive > cfg.Concurrency {
		t.Fatalf("max active Stores = %d, concurrency = %d", client.maxActive, cfg.Concurrency)
	}
	if client.maxActive < 2 {
		t.Fatalf("max active Stores = %d, want concurrent execution", client.maxActive)
	}
}

func TestMaintenanceOperationsUseTheirOwnLowerConcurrency(t *testing.T) {
	cfg := fastRunnerConfig()
	cfg.Devices = 24
	cfg.Concurrency = 16
	cfg.MaintenanceConcurrency = 3

	var mu sync.Mutex
	active := 0
	maximum := 0
	results := parallelDeviceOperation(context.Background(), cfg, func(context.Context, int) (int64, error) {
		mu.Lock()
		active++
		if active > maximum {
			maximum = active
		}
		mu.Unlock()
		time.Sleep(time.Millisecond)
		mu.Lock()
		active--
		mu.Unlock()
		return 1, nil
	})
	for range results {
	}

	if maximum > cfg.MaintenanceConcurrency {
		t.Fatalf("max active maintenance operations = %d, limit = %d", maximum, cfg.MaintenanceConcurrency)
	}
	if maximum < 2 {
		t.Fatalf("max active maintenance operations = %d, want concurrent execution", maximum)
	}
}

func TestRunAggregatesFailuresAndReadbackMismatch(t *testing.T) {
	cfg := fastRunnerConfig()
	client := newFakeEventClient()
	client.failStore = func(sample Sample) error {
		if sample.Sequence%4 == 0 {
			return fmt.Errorf("HTTP 503 unavailable")
		}
		return nil
	}
	mismatchDevice := DeviceName(cfg.RunID, 1)
	client.countOverrides[mismatchDevice] = 0
	client.failCount[DeviceName(cfg.RunID, 2)] = fmt.Errorf("count unavailable")
	client.failDelete[DeviceName(cfg.RunID, 3)] = fmt.Errorf("delete unavailable")

	report := Run(context.Background(), cfg, client)

	if report.Succeeded != 12 || report.Failed != 4 || report.ErrorGroups["http-503"] != 4 {
		t.Fatalf("unexpected failure aggregation: %#v", report)
	}
	if report.Verification.Matched || report.Verification.MismatchedDevices == 0 || len(report.Verification.Errors) != 1 {
		t.Fatalf("unexpected verification: %#v", report.Verification)
	}
	if len(report.Cleanup.Errors) != 1 || report.Pass {
		t.Fatalf("unexpected cleanup/pass: cleanup=%#v pass=%v", report.Cleanup, report.Pass)
	}
}

func TestMaintenanceErrorDetailsAreBounded(t *testing.T) {
	cfg := fastRunnerConfig()
	cfg.Devices = 24
	client := newFakeEventClient()
	expected := make(map[string]int, cfg.Devices)
	for index := 0; index < cfg.Devices; index++ {
		deviceName := DeviceName(cfg.RunID, index)
		expected[deviceName] = 1
		client.failCount[deviceName] = fmt.Errorf("count unavailable")
		client.failDelete[deviceName] = fmt.Errorf("delete unavailable")
	}

	verification := verifyStoredEvents(context.Background(), cfg, client, expected)
	cleanup := cleanupStoredEvents(context.Background(), cfg, client)

	if len(verification.Errors) != maxDetailedOperationErrors || verification.SuppressedErrors != 4 {
		t.Fatalf("verification errors=%d suppressed=%d", len(verification.Errors), verification.SuppressedErrors)
	}
	if len(cleanup.Errors) != maxDetailedOperationErrors || cleanup.SuppressedErrors != 4 {
		t.Fatalf("cleanup errors=%d suppressed=%d", len(cleanup.Errors), cleanup.SuppressedErrors)
	}
}

func TestRunStopsSchedulingWhenContextIsCancelled(t *testing.T) {
	cfg := fastRunnerConfig()
	cfg.Duration = time.Second
	client := newFakeEventClient()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	report := Run(ctx, cfg, client)

	if report.Attempted >= report.Planned {
		t.Fatalf("attempted %d events after cancellation, planned %d", report.Attempted, report.Planned)
	}
	if report.Pass {
		t.Fatal("cancelled run unexpectedly passed")
	}
}

func TestErrorClassIsBoundedAndStable(t *testing.T) {
	tests := []struct {
		err  error
		want string
	}{
		{context.DeadlineExceeded, "timeout"},
		{fmt.Errorf("POST path returned HTTP 503: unavailable"), "http-503"},
		{fmt.Errorf("response event ID mismatch"), "response-id-mismatch"},
		{fmt.Errorf("dial tcp: connection refused"), "transport"},
	}
	for _, tt := range tests {
		if got := ErrorClass(tt.err); got != tt.want {
			t.Errorf("ErrorClass(%q) = %q, want %q", tt.err, got, tt.want)
		}
	}
}

func TestParseConfigUsesSafeScaleBaselineDefaults(t *testing.T) {
	cfg, err := ParseConfig(nil, &bytes.Buffer{})
	if err != nil {
		t.Fatalf("ParseConfig() error = %v", err)
	}
	if cfg.Devices != 1000 || math.Abs(cfg.PerDeviceHz-(1.0/60.0)) > 1e-9 || cfg.Duration != time.Minute || cfg.Concurrency != 128 || cfg.MaintenanceConcurrency != 8 {
		t.Fatalf("unexpected scale defaults: %#v", cfg)
	}
	if cfg.BaseURL != "http://edgex-core-data.edgex-system.svc.cluster.local:59880" {
		t.Fatalf("base URL = %q", cfg.BaseURL)
	}
	if !cfg.Verify || !cfg.Cleanup || !runIDPattern.MatchString(cfg.RunID) {
		t.Fatalf("unexpected safety defaults: %#v", cfg)
	}
}

func TestRunCLIEmitsMachineReadablePassReport(t *testing.T) {
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	client := newFakeEventClient()
	args := []string{
		"--run-id=cli-test",
		"--base-url=http://core-data.test",
		"--devices=2",
		"--per-device-hz=1000",
		"--duration=2ms",
		"--concurrency=2",
		"--min-rate-ratio=0.01",
	}

	exitCode := RunCLI(context.Background(), args, stdout, stderr, func(Config) EventClient { return client })
	if exitCode != 0 {
		t.Fatalf("RunCLI() exit = %d, stderr = %q, stdout = %q", exitCode, stderr.String(), stdout.String())
	}
	var report Report
	if err := json.Unmarshal(stdout.Bytes(), &report); err != nil {
		t.Fatalf("stdout is not a JSON report: %v\n%s", err, stdout.String())
	}
	if !report.Pass || report.RunID != "cli-test" || report.Planned != 4 || report.Succeeded != 4 {
		t.Fatalf("unexpected report: %#v", report)
	}
	if stderr.Len() != 0 {
		t.Fatalf("stderr = %q, want empty", stderr.String())
	}
}

func TestRunCLIRejectsInvalidConfiguration(t *testing.T) {
	stdout := &bytes.Buffer{}
	stderr := &bytes.Buffer{}
	exitCode := RunCLI(
		context.Background(),
		[]string{"--run-id=Bad_ID"},
		stdout,
		stderr,
		func(Config) EventClient { t.Fatal("client factory called for invalid config"); return nil },
	)
	if exitCode != 2 || !strings.Contains(stderr.String(), "run-id") || stdout.Len() != 0 {
		t.Fatalf("exit=%d stdout=%q stderr=%q", exitCode, stdout.String(), stderr.String())
	}
}
