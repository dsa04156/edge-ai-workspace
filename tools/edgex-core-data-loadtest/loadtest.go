package main

import (
	"fmt"
	"math"
	"net/url"
	"regexp"
	"sort"
	"time"
)

var runIDPattern = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)

type Config struct {
	BaseURL        string
	RunID          string
	Devices        int
	PerDeviceHz    float64
	Duration       time.Duration
	Concurrency    int
	RequestTimeout time.Duration
	MaxErrorRate   float64
	MaxP95         time.Duration
	MinRateRatio   float64
	Verify         bool
	Cleanup        bool
}

func (c Config) Validate() error {
	parsed, err := url.Parse(c.BaseURL)
	if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return fmt.Errorf("base-url must be an absolute HTTP URL")
	}
	if !runIDPattern.MatchString(c.RunID) {
		return fmt.Errorf("run-id must contain only lowercase letters, digits, and hyphens")
	}
	if c.Devices <= 0 {
		return fmt.Errorf("devices must be greater than zero")
	}
	if c.PerDeviceHz <= 0 || math.IsNaN(c.PerDeviceHz) || math.IsInf(c.PerDeviceHz, 0) {
		return fmt.Errorf("per-device-hz must be a finite positive number")
	}
	if c.Duration <= 0 {
		return fmt.Errorf("duration must be greater than zero")
	}
	if c.Concurrency <= 0 {
		return fmt.Errorf("concurrency must be greater than zero")
	}
	if c.RequestTimeout <= 0 {
		return fmt.Errorf("request-timeout must be greater than zero")
	}
	if c.MaxErrorRate < 0 || c.MaxErrorRate > 1 || math.IsNaN(c.MaxErrorRate) {
		return fmt.Errorf("max-error-rate must be between zero and one")
	}
	if c.MaxP95 <= 0 {
		return fmt.Errorf("max-p95 must be greater than zero")
	}
	if c.MinRateRatio <= 0 || c.MinRateRatio > 1 || math.IsNaN(c.MinRateRatio) {
		return fmt.Errorf("min-rate-ratio must be greater than zero and at most one")
	}
	return nil
}

func (c Config) TargetEPS() float64 {
	return float64(c.Devices) * c.PerDeviceHz
}

func PlannedEvents(c Config) int {
	return int(math.Round(c.TargetEPS() * c.Duration.Seconds()))
}

type LatencyReport struct {
	P50Milliseconds float64 `json:"p50Ms"`
	P95Milliseconds float64 `json:"p95Ms"`
	P99Milliseconds float64 `json:"p99Ms"`
	MaxMilliseconds float64 `json:"maxMs"`
}

type VerificationReport struct {
	Enabled   bool     `json:"enabled"`
	Persisted int      `json:"persisted"`
	Matched   bool     `json:"matched"`
	Errors    []string `json:"errors,omitempty"`
}

type CleanupReport struct {
	Enabled bool     `json:"enabled"`
	Deleted int      `json:"deletedDevices"`
	Errors  []string `json:"errors,omitempty"`
}

type Report struct {
	Planned      int                `json:"planned"`
	Attempted    int                `json:"attempted"`
	Succeeded    int                `json:"succeeded"`
	Failed       int                `json:"failed"`
	TargetEPS    float64            `json:"targetEventsPerSecond"`
	AchievedEPS  float64            `json:"achievedEventsPerSecond"`
	ErrorRate    float64            `json:"errorRate"`
	Latency      LatencyReport      `json:"latency"`
	Verification VerificationReport `json:"verification"`
	Cleanup      CleanupReport      `json:"cleanup"`
}

func Percentile(values []time.Duration, percentile float64) time.Duration {
	if len(values) == 0 {
		return 0
	}
	ordered := append([]time.Duration(nil), values...)
	sort.Slice(ordered, func(i, j int) bool { return ordered[i] < ordered[j] })
	if percentile <= 0 {
		return ordered[0]
	}
	if percentile >= 1 {
		return ordered[len(ordered)-1]
	}
	rank := int(math.Ceil(percentile * float64(len(ordered))))
	return ordered[rank-1]
}

func Evaluate(cfg Config, report Report) []string {
	reasons := make([]string, 0)
	if report.Attempted != report.Planned {
		reasons = append(reasons, fmt.Sprintf("attempted %d events, planned %d", report.Attempted, report.Planned))
	}
	if report.Succeeded != report.Planned {
		reasons = append(reasons, fmt.Sprintf("succeeded %d events, planned %d", report.Succeeded, report.Planned))
	}
	if report.ErrorRate > cfg.MaxErrorRate {
		reasons = append(reasons, fmt.Sprintf("error rate %.6f exceeds %.6f", report.ErrorRate, cfg.MaxErrorRate))
	}
	if report.Latency.P95Milliseconds > float64(cfg.MaxP95)/float64(time.Millisecond) {
		reasons = append(reasons, fmt.Sprintf("p95 %.3fms exceeds %.3fms", report.Latency.P95Milliseconds, float64(cfg.MaxP95)/float64(time.Millisecond)))
	}
	minimumRate := report.TargetEPS * cfg.MinRateRatio
	if report.AchievedEPS < minimumRate {
		reasons = append(reasons, fmt.Sprintf("achieved rate %.3f events/s is below %.3f events/s", report.AchievedEPS, minimumRate))
	}
	if cfg.Verify && (!report.Verification.Matched || report.Verification.Persisted != report.Succeeded) {
		reasons = append(reasons, fmt.Sprintf("readback persisted %d events, succeeded %d", report.Verification.Persisted, report.Succeeded))
	}
	if cfg.Verify && len(report.Verification.Errors) > 0 {
		reasons = append(reasons, fmt.Sprintf("verification errors: %d", len(report.Verification.Errors)))
	}
	if cfg.Cleanup && len(report.Cleanup.Errors) > 0 {
		reasons = append(reasons, fmt.Sprintf("cleanup errors: %d", len(report.Cleanup.Errors)))
	}
	return reasons
}
