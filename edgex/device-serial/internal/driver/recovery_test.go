package driver

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParseSerialRecoveryConfig(t *testing.T) {
	defaults, err := parseSerialRecoveryConfig(nil)
	require.NoError(t, err)
	assert.Equal(t, 400*time.Millisecond, defaults.target)
	assert.Equal(t, defaultSerialReconnectDelays, defaults.reconnectDelays)

	configured, err := parseSerialRecoveryConfig(map[string]string{
		serialRecoveryTargetConfig:  "350ms",
		serialReconnectDelaysConfig: "10ms, 20ms,100ms",
	})
	require.NoError(t, err)
	assert.Equal(t, 350*time.Millisecond, configured.target)
	assert.Equal(t, []time.Duration{
		10 * time.Millisecond,
		20 * time.Millisecond,
		100 * time.Millisecond,
	}, configured.reconnectDelays)
}

func TestParseSerialRecoveryConfigRejectsUnsafeValues(t *testing.T) {
	tests := []map[string]string{
		{serialRecoveryTargetConfig: "0s"},
		{serialRecoveryTargetConfig: "not-a-duration"},
		{serialReconnectDelaysConfig: ""},
		{serialReconnectDelaysConfig: "100ms,50ms"},
		{serialReconnectDelaysConfig: "31s"},
	}
	for _, values := range tests {
		_, err := parseSerialRecoveryConfig(values)
		assert.Error(t, err, values)
	}
}

func TestSerialRecoveryMetricsExposeTargetAndMisses(t *testing.T) {
	metrics := newSerialRecoveryMetrics(400 * time.Millisecond)
	detectedAt := time.Date(2026, time.September, 1, 0, 0, 0, 0, time.UTC)
	metrics.observeStarted()
	metrics.observeCompleted(RecoveryObservation{
		DetectedAt:  detectedAt,
		PortReadyAt: detectedAt.Add(300 * time.Millisecond),
		FirstByteAt: detectedAt.Add(350 * time.Millisecond),
		ResumedAt:   detectedAt.Add(401 * time.Millisecond),
		Duration:    401 * time.Millisecond,
		Attempts:    4,
	})

	response := metrics.snapshot()
	assert.Equal(t, float64(400), response.TargetMs)
	assert.Equal(t, int64(1), response.Detected)
	assert.Equal(t, int64(1), response.Completed)
	assert.False(t, response.InProgress)
	assert.Equal(t, int64(1), response.TargetMisses)
	require.NotNil(t, response.Last)
	assert.Equal(t, detectedAt.Add(300*time.Millisecond).UnixNano(), response.Last.PortReadyAtUnixNano)
	assert.Equal(t, detectedAt.Add(350*time.Millisecond).UnixNano(), response.Last.FirstByteAtUnixNano)
	assert.Equal(t, float64(300), response.Last.DetectionToPortReadyMs)
	assert.Equal(t, float64(50), response.Last.PortReadyToFirstByteMs)
	assert.Equal(t, float64(51), response.Last.FirstByteToResumeMs)
	assert.Equal(t, float64(401), response.Last.DurationMs)
	assert.Equal(t, 4, response.Last.Attempts)
	assert.False(t, response.Last.WithinTarget)

	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodGet, serialRecoveryStatsRoute, nil)
	context := echo.New().NewContext(request, recorder)
	require.NoError(t, metrics.stats(context))
	assert.Equal(t, http.StatusOK, recorder.Code)
	assert.Contains(t, recorder.Body.String(), `"targetMs":400`)
	assert.Contains(t, recorder.Body.String(), `"targetMisses":1`)
}
