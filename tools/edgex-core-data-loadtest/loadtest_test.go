package main

import (
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
