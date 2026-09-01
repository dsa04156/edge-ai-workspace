package driver

import (
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	bootstrapInterfaces "github.com/edgexfoundry/go-mod-bootstrap/v4/bootstrap/interfaces"
	"github.com/labstack/echo/v4"
	gometrics "github.com/rcrowley/go-metrics"
)

const (
	serialRecoveryTargetConfig  = "SerialRecoveryTarget"
	serialReconnectDelaysConfig = "SerialReconnectDelays"
	serialRecoveryStatsRoute    = "/api/v3/serial-recovery/stats"

	serialRecoveryDetectedMetric       = "SerialRecoveryDetected"
	serialRecoveryCompletedMetric      = "SerialRecoveryCompleted"
	serialRecoveryLastDurationMsMetric = "SerialRecoveryLastDurationMs"
	serialRecoveryLastAttemptsMetric   = "SerialRecoveryLastAttempts"
	serialRecoveryTargetMissesMetric   = "SerialRecoveryTargetMisses"

	defaultSerialRecoveryTarget = 400 * time.Millisecond
	maxSerialReconnectSteps     = 16
	maxSerialReconnectDelay     = 30 * time.Second
)

var defaultSerialReconnectDelays = []time.Duration{
	25 * time.Millisecond,
	50 * time.Millisecond,
	100 * time.Millisecond,
	200 * time.Millisecond,
	time.Second,
	2 * time.Second,
	4 * time.Second,
	8 * time.Second,
	16 * time.Second,
	30 * time.Second,
}

type RecoveryObservation struct {
	DetectedAt  time.Time
	PortReadyAt time.Time
	FirstByteAt time.Time
	ResumedAt   time.Time
	Duration    time.Duration
	Attempts    int
}

type serialRecoveryConfig struct {
	target          time.Duration
	reconnectDelays []time.Duration
}

func parseSerialRecoveryConfig(values map[string]string) (serialRecoveryConfig, error) {
	config := serialRecoveryConfig{
		target:          defaultSerialRecoveryTarget,
		reconnectDelays: append([]time.Duration(nil), defaultSerialReconnectDelays...),
	}

	if raw, found := values[serialRecoveryTargetConfig]; found {
		value, err := time.ParseDuration(strings.TrimSpace(raw))
		if err != nil || value <= 0 {
			return serialRecoveryConfig{}, fmt.Errorf(
				"%s must be a positive duration",
				serialRecoveryTargetConfig,
			)
		}
		config.target = value
	}
	if raw, found := values[serialReconnectDelaysConfig]; found {
		delays, err := parseSerialReconnectDelays(raw)
		if err != nil {
			return serialRecoveryConfig{}, err
		}
		config.reconnectDelays = delays
	}
	return config, nil
}

func parseSerialReconnectDelays(raw string) ([]time.Duration, error) {
	parts := strings.Split(raw, ",")
	if len(parts) == 0 || len(parts) > maxSerialReconnectSteps {
		return nil, fmt.Errorf(
			"%s must contain 1 through %d comma-separated durations",
			serialReconnectDelaysConfig,
			maxSerialReconnectSteps,
		)
	}
	delays := make([]time.Duration, 0, len(parts))
	for index, part := range parts {
		value, err := time.ParseDuration(strings.TrimSpace(part))
		if err != nil || value <= 0 || value > maxSerialReconnectDelay {
			return nil, fmt.Errorf(
				"%s entry %d must be a positive duration no greater than %s",
				serialReconnectDelaysConfig,
				index+1,
				maxSerialReconnectDelay,
			)
		}
		if index > 0 && value < delays[index-1] {
			return nil, fmt.Errorf(
				"%s entries must be nondecreasing",
				serialReconnectDelaysConfig,
			)
		}
		delays = append(delays, value)
	}
	return delays, nil
}

type serialRecoveryMetrics struct {
	mu             sync.RWMutex
	target         time.Duration
	detected       gometrics.Counter
	completed      gometrics.Counter
	lastDurationMs gometrics.GaugeFloat64
	lastAttempts   gometrics.Gauge
	targetMisses   gometrics.Counter
	last           *RecoveryObservation
}

func newSerialRecoveryMetrics(target time.Duration) *serialRecoveryMetrics {
	return &serialRecoveryMetrics{
		target:         target,
		detected:       gometrics.NewCounter(),
		completed:      gometrics.NewCounter(),
		lastDurationMs: gometrics.NewGaugeFloat64(),
		lastAttempts:   gometrics.NewGauge(),
		targetMisses:   gometrics.NewCounter(),
	}
}

func (metrics *serialRecoveryMetrics) register(
	manager bootstrapInterfaces.MetricsManager,
) error {
	if manager == nil {
		return nil
	}
	registrations := []struct {
		name string
		item interface{}
	}{
		{name: serialRecoveryDetectedMetric, item: metrics.detected},
		{name: serialRecoveryCompletedMetric, item: metrics.completed},
		{name: serialRecoveryLastDurationMsMetric, item: metrics.lastDurationMs},
		{name: serialRecoveryLastAttemptsMetric, item: metrics.lastAttempts},
		{name: serialRecoveryTargetMissesMetric, item: metrics.targetMisses},
	}
	for _, registration := range registrations {
		if err := manager.Register(registration.name, registration.item, nil); err != nil {
			return fmt.Errorf("register metric %s: %w", registration.name, err)
		}
	}
	return nil
}

func (metrics *serialRecoveryMetrics) observeStarted() {
	metrics.mu.Lock()
	defer metrics.mu.Unlock()
	metrics.detected.Inc(1)
}

func (metrics *serialRecoveryMetrics) observeCompleted(observation RecoveryObservation) {
	metrics.mu.Lock()
	defer metrics.mu.Unlock()
	copy := observation
	metrics.last = &copy
	metrics.completed.Inc(1)
	metrics.lastDurationMs.Update(float64(observation.Duration) / float64(time.Millisecond))
	metrics.lastAttempts.Update(int64(observation.Attempts))
	if observation.Duration > metrics.target {
		metrics.targetMisses.Inc(1)
	}
}

type serialRecoveryLastResponse struct {
	DetectedAtUnixNano     int64   `json:"detectedAtUnixNano"`
	PortReadyAtUnixNano    int64   `json:"portReadyAtUnixNano"`
	FirstByteAtUnixNano    int64   `json:"firstByteAtUnixNano"`
	ResumedAtUnixNano      int64   `json:"resumedAtUnixNano"`
	DetectionToPortReadyMs float64 `json:"detectionToPortReadyMs"`
	PortReadyToFirstByteMs float64 `json:"portReadyToFirstByteMs"`
	FirstByteToResumeMs    float64 `json:"firstByteToResumeMs"`
	DurationMs             float64 `json:"durationMs"`
	Attempts               int     `json:"attempts"`
	WithinTarget           bool    `json:"withinTarget"`
}

type serialRecoveryStatsResponse struct {
	APIVersion   string                      `json:"apiVersion"`
	StatusCode   int                         `json:"statusCode"`
	TargetMs     float64                     `json:"targetMs"`
	Detected     int64                       `json:"detected"`
	Completed    int64                       `json:"completed"`
	InProgress   bool                        `json:"inProgress"`
	TargetMisses int64                       `json:"targetMisses"`
	Last         *serialRecoveryLastResponse `json:"last"`
}

func (metrics *serialRecoveryMetrics) snapshot() serialRecoveryStatsResponse {
	metrics.mu.RLock()
	defer metrics.mu.RUnlock()

	detected := metrics.detected.Count()
	completed := metrics.completed.Count()
	response := serialRecoveryStatsResponse{
		APIVersion:   "v3",
		StatusCode:   http.StatusOK,
		TargetMs:     float64(metrics.target) / float64(time.Millisecond),
		Detected:     detected,
		Completed:    completed,
		InProgress:   detected > completed,
		TargetMisses: metrics.targetMisses.Count(),
	}

	last := metrics.last
	if last != nil {
		response.Last = &serialRecoveryLastResponse{
			DetectedAtUnixNano:     unixNanoOrZero(last.DetectedAt),
			PortReadyAtUnixNano:    unixNanoOrZero(last.PortReadyAt),
			FirstByteAtUnixNano:    unixNanoOrZero(last.FirstByteAt),
			ResumedAtUnixNano:      unixNanoOrZero(last.ResumedAt),
			DetectionToPortReadyMs: elapsedMilliseconds(last.DetectedAt, last.PortReadyAt),
			PortReadyToFirstByteMs: elapsedMilliseconds(last.PortReadyAt, last.FirstByteAt),
			FirstByteToResumeMs:    elapsedMilliseconds(last.FirstByteAt, last.ResumedAt),
			DurationMs:             float64(last.Duration) / float64(time.Millisecond),
			Attempts:               last.Attempts,
			WithinTarget:           last.Duration <= metrics.target,
		}
	}
	return response
}

func unixNanoOrZero(value time.Time) int64 {
	if value.IsZero() {
		return 0
	}
	return value.UnixNano()
}

func elapsedMilliseconds(start time.Time, end time.Time) float64 {
	if start.IsZero() || end.IsZero() || end.Before(start) {
		return 0
	}
	return float64(end.Sub(start)) / float64(time.Millisecond)
}

func (metrics *serialRecoveryMetrics) stats(context echo.Context) error {
	return context.JSON(http.StatusOK, metrics.snapshot())
}
