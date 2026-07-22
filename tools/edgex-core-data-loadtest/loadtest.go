package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

var runIDPattern = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$`)
var httpStatusPattern = regexp.MustCompile(`HTTP ([0-9]{3})`)

const (
	loadtestServiceName = "core-data-loadtest"
	loadtestProfileName = "loadtest-profile-v1"
	loadtestSourceName  = "value"
	loadtestRunIDTag    = "loadTestRunId"
	maxResponseBodySize = 64 << 10
)

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
	Enabled           bool     `json:"enabled"`
	CheckedDevices    int      `json:"checkedDevices"`
	Persisted         int      `json:"persisted"`
	Matched           bool     `json:"matched"`
	MismatchedDevices int      `json:"mismatchedDevices"`
	Errors            []string `json:"errors,omitempty"`
}

type CleanupReport struct {
	Enabled bool     `json:"enabled"`
	Deleted int      `json:"deletedDevices"`
	Errors  []string `json:"errors,omitempty"`
}

type Report struct {
	RunID        string             `json:"runId"`
	StartedAt    time.Time          `json:"startedAt"`
	FinishedAt   time.Time          `json:"finishedAt"`
	DeviceCount  int                `json:"deviceCount"`
	PerDeviceHz  float64            `json:"perDeviceHz"`
	DurationSecs float64            `json:"loadDurationSeconds"`
	Planned      int                `json:"planned"`
	Attempted    int                `json:"attempted"`
	Succeeded    int                `json:"succeeded"`
	Failed       int                `json:"failed"`
	TargetEPS    float64            `json:"targetEventsPerSecond"`
	AchievedEPS  float64            `json:"achievedEventsPerSecond"`
	ErrorRate    float64            `json:"errorRate"`
	Latency      LatencyReport      `json:"latency"`
	ErrorGroups  map[string]int     `json:"errorGroups,omitempty"`
	Verification VerificationReport `json:"verification"`
	Cleanup      CleanupReport      `json:"cleanup"`
	Pass         bool               `json:"pass"`
	Reasons      []string           `json:"reasons,omitempty"`
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

type Sample struct {
	DeviceName string
	Sequence   int
	Origin     int64
	Value      float64
}

type ReadingDTO struct {
	ID           string `json:"id"`
	Origin       int64  `json:"origin"`
	DeviceName   string `json:"deviceName"`
	ResourceName string `json:"resourceName"`
	ProfileName  string `json:"profileName"`
	ValueType    string `json:"valueType"`
	Value        string `json:"value"`
}

type EventDTO struct {
	APIVersion  string            `json:"apiVersion"`
	ID          string            `json:"id"`
	DeviceName  string            `json:"deviceName"`
	ProfileName string            `json:"profileName"`
	SourceName  string            `json:"sourceName"`
	Origin      int64             `json:"origin"`
	Readings    []ReadingDTO      `json:"readings"`
	Tags        map[string]string `json:"tags,omitempty"`
}

type AddEventRequest struct {
	APIVersion string   `json:"apiVersion"`
	RequestID  string   `json:"requestId"`
	Event      EventDTO `json:"event"`
}

func BuildEvent(runID string, sample Sample) (AddEventRequest, error) {
	requestID, err := newUUID()
	if err != nil {
		return AddEventRequest{}, fmt.Errorf("generate request ID: %w", err)
	}
	eventID, err := newUUID()
	if err != nil {
		return AddEventRequest{}, fmt.Errorf("generate event ID: %w", err)
	}
	readingID, err := newUUID()
	if err != nil {
		return AddEventRequest{}, fmt.Errorf("generate reading ID: %w", err)
	}

	reading := ReadingDTO{
		ID:           readingID,
		Origin:       sample.Origin,
		DeviceName:   sample.DeviceName,
		ResourceName: loadtestSourceName,
		ProfileName:  loadtestProfileName,
		ValueType:    "Float64",
		Value:        strconv.FormatFloat(sample.Value, 'f', -1, 64),
	}
	return AddEventRequest{
		APIVersion: "v3",
		RequestID:  requestID,
		Event: EventDTO{
			APIVersion:  "v3",
			ID:          eventID,
			DeviceName:  sample.DeviceName,
			ProfileName: loadtestProfileName,
			SourceName:  loadtestSourceName,
			Origin:      sample.Origin,
			Readings:    []ReadingDTO{reading},
			Tags:        map[string]string{loadtestRunIDTag: runID},
		},
	}, nil
}

func newUUID() (string, error) {
	var value [16]byte
	if _, err := rand.Read(value[:]); err != nil {
		return "", err
	}
	value[6] = (value[6] & 0x0f) | 0x40
	value[8] = (value[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", value[0:4], value[4:6], value[6:8], value[8:10], value[10:16]), nil
}

type StoreResult struct {
	EventID string
	Latency time.Duration
	Err     error
}

type HTTPClient struct {
	baseURL        string
	runID          string
	requestTimeout time.Duration
	httpClient     *http.Client
}

func NewHTTPClient(cfg Config) *HTTPClient {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConns = cfg.Concurrency * 2
	transport.MaxIdleConnsPerHost = cfg.Concurrency
	transport.MaxConnsPerHost = cfg.Concurrency
	transport.IdleConnTimeout = 90 * time.Second
	return &HTTPClient{
		baseURL:        strings.TrimRight(cfg.BaseURL, "/"),
		runID:          cfg.RunID,
		requestTimeout: cfg.RequestTimeout,
		httpClient:     &http.Client{Transport: transport},
	}
}

func (c *HTTPClient) Store(ctx context.Context, sample Sample) StoreResult {
	started := time.Now()
	request, err := BuildEvent(c.runID, sample)
	if err != nil {
		return StoreResult{Latency: time.Since(started), Err: err}
	}
	payload, err := json.Marshal(request)
	if err != nil {
		return StoreResult{Latency: time.Since(started), Err: fmt.Errorf("encode event: %w", err)}
	}
	path := fmt.Sprintf(
		"/api/v3/event/%s/%s/%s/%s",
		url.PathEscape(loadtestServiceName),
		url.PathEscape(loadtestProfileName),
		url.PathEscape(sample.DeviceName),
		url.PathEscape(loadtestSourceName),
	)

	var response struct {
		ID string `json:"id"`
	}
	if err := c.doJSON(ctx, http.MethodPost, path, payload, http.StatusCreated, &response); err != nil {
		return StoreResult{Latency: time.Since(started), Err: err}
	}
	if response.ID != request.Event.ID {
		return StoreResult{
			Latency: time.Since(started),
			Err:     fmt.Errorf("response event ID %q does not match request event ID %q", response.ID, request.Event.ID),
		}
	}
	return StoreResult{EventID: request.Event.ID, Latency: time.Since(started)}
}

func (c *HTTPClient) Count(ctx context.Context, deviceName string) (int64, error) {
	path := "/api/v3/event/device/name/" + url.PathEscape(deviceName) + "?limit=1"
	var response struct {
		TotalCount int64 `json:"totalCount"`
	}
	if err := c.doJSON(ctx, http.MethodGet, path, nil, http.StatusOK, &response); err != nil {
		return 0, err
	}
	return response.TotalCount, nil
}

func (c *HTTPClient) Delete(ctx context.Context, deviceName string) error {
	path := "/api/v3/event/device/name/" + url.PathEscape(deviceName)
	return c.doJSON(ctx, http.MethodDelete, path, nil, http.StatusAccepted, nil)
}

func (c *HTTPClient) doJSON(ctx context.Context, method string, path string, payload []byte, expectedStatus int, destination any) error {
	requestContext, cancel := context.WithTimeout(ctx, c.requestTimeout)
	defer cancel()

	request, err := http.NewRequestWithContext(requestContext, method, c.baseURL+path, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("create %s request: %w", method, err)
	}
	request.Header.Set("Accept", "application/json")
	if payload != nil {
		request.Header.Set("Content-Type", "application/json")
	}

	response, err := c.httpClient.Do(request)
	if err != nil {
		return fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer response.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(response.Body, maxResponseBodySize))
	if readErr != nil {
		return fmt.Errorf("read %s %s response: %w", method, path, readErr)
	}
	if response.StatusCode != expectedStatus {
		return fmt.Errorf("%s %s returned HTTP %d: %s", method, path, response.StatusCode, strings.TrimSpace(string(body)))
	}
	if destination != nil {
		if err := json.Unmarshal(body, destination); err != nil {
			return fmt.Errorf("decode %s %s response: %w", method, path, err)
		}
	}
	return nil
}

type EventClient interface {
	Store(context.Context, Sample) StoreResult
	Count(context.Context, string) (int64, error)
	Delete(context.Context, string) error
}

type storeOutcome struct {
	deviceName string
	result     StoreResult
}

func DeviceName(runID string, index int) string {
	return fmt.Sprintf("loadtest-%s-%04d", runID, index)
}

func Run(ctx context.Context, cfg Config, client EventClient) Report {
	started := time.Now().UTC()
	planned := PlannedEvents(cfg)
	report := Report{
		RunID:        cfg.RunID,
		StartedAt:    started,
		DeviceCount:  cfg.Devices,
		PerDeviceHz:  cfg.PerDeviceHz,
		Planned:      planned,
		TargetEPS:    cfg.TargetEPS(),
		ErrorGroups:  make(map[string]int),
		Verification: VerificationReport{Enabled: cfg.Verify},
		Cleanup:      CleanupReport{Enabled: cfg.Cleanup},
	}

	jobs := make(chan int, cfg.Concurrency*2)
	outcomes := make(chan storeOutcome, cfg.Concurrency*2)
	var workers sync.WaitGroup
	for worker := 0; worker < cfg.Concurrency; worker++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for sequence := range jobs {
				deviceName := DeviceName(cfg.RunID, sequence%cfg.Devices)
				sample := Sample{
					DeviceName: deviceName,
					Sequence:   sequence,
					Origin:     time.Now().UnixNano(),
					Value:      float64(sequence%10000) / 100,
				}
				outcomes <- storeOutcome{deviceName: deviceName, result: client.Store(ctx, sample)}
			}
		}()
	}

	go func() {
		defer close(jobs)
		for sequence := 0; sequence < planned; sequence++ {
			if !waitUntil(ctx, started.Add(scheduleOffset(sequence, report.TargetEPS))) {
				return
			}
			select {
			case jobs <- sequence:
			case <-ctx.Done():
				return
			}
		}
	}()

	go func() {
		workers.Wait()
		close(outcomes)
	}()

	latencies := make([]time.Duration, 0, planned)
	expectedByDevice := make(map[string]int, cfg.Devices)
	for outcome := range outcomes {
		report.Attempted++
		if outcome.result.Err != nil {
			report.Failed++
			report.ErrorGroups[ErrorClass(outcome.result.Err)]++
			continue
		}
		report.Succeeded++
		expectedByDevice[outcome.deviceName]++
		latencies = append(latencies, outcome.result.Latency)
	}

	loadFinished := time.Now().UTC()
	report.DurationSecs = loadFinished.Sub(started).Seconds()
	if report.DurationSecs > 0 {
		report.AchievedEPS = float64(report.Succeeded) / report.DurationSecs
	}
	if report.Attempted > 0 {
		report.ErrorRate = float64(report.Failed) / float64(report.Attempted)
	}
	report.Latency = summarizeLatencies(latencies)

	maintenanceContext := context.Background()
	if cfg.Verify {
		report.Verification = verifyStoredEvents(maintenanceContext, cfg, client, expectedByDevice)
	}
	if cfg.Cleanup {
		report.Cleanup = cleanupStoredEvents(maintenanceContext, cfg, client)
	}
	report.FinishedAt = time.Now().UTC()
	report.Reasons = Evaluate(cfg, report)
	report.Pass = len(report.Reasons) == 0
	return report
}

func scheduleOffset(sequence int, eventsPerSecond float64) time.Duration {
	if eventsPerSecond <= 0 {
		return 0
	}
	return time.Duration(float64(sequence) * float64(time.Second) / eventsPerSecond)
}

func waitUntil(ctx context.Context, target time.Time) bool {
	delay := time.Until(target)
	if delay <= 0 {
		select {
		case <-ctx.Done():
			return false
		default:
			return true
		}
	}
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-ctx.Done():
		return false
	}
}

func summarizeLatencies(values []time.Duration) LatencyReport {
	maximum := time.Duration(0)
	for _, value := range values {
		if value > maximum {
			maximum = value
		}
	}
	toMilliseconds := func(value time.Duration) float64 {
		return float64(value) / float64(time.Millisecond)
	}
	return LatencyReport{
		P50Milliseconds: toMilliseconds(Percentile(values, 0.50)),
		P95Milliseconds: toMilliseconds(Percentile(values, 0.95)),
		P99Milliseconds: toMilliseconds(Percentile(values, 0.99)),
		MaxMilliseconds: toMilliseconds(maximum),
	}
}

type deviceOperationResult struct {
	index int
	count int64
	err   error
}

func verifyStoredEvents(ctx context.Context, cfg Config, client EventClient, expected map[string]int) VerificationReport {
	report := VerificationReport{Enabled: true}
	results := parallelDeviceOperation(ctx, cfg, func(operationContext context.Context, index int) (int64, error) {
		return client.Count(operationContext, DeviceName(cfg.RunID, index))
	})
	for result := range results {
		report.CheckedDevices++
		deviceName := DeviceName(cfg.RunID, result.index)
		if result.err != nil {
			report.Errors = append(report.Errors, fmt.Sprintf("%s: %v", deviceName, result.err))
			continue
		}
		report.Persisted += int(result.count)
		if result.count != int64(expected[deviceName]) {
			report.MismatchedDevices++
		}
	}
	report.Matched = len(report.Errors) == 0 && report.MismatchedDevices == 0
	return report
}

func cleanupStoredEvents(ctx context.Context, cfg Config, client EventClient) CleanupReport {
	report := CleanupReport{Enabled: true}
	results := parallelDeviceOperation(ctx, cfg, func(operationContext context.Context, index int) (int64, error) {
		return 0, client.Delete(operationContext, DeviceName(cfg.RunID, index))
	})
	for result := range results {
		if result.err != nil {
			report.Errors = append(report.Errors, fmt.Sprintf("%s: %v", DeviceName(cfg.RunID, result.index), result.err))
			continue
		}
		report.Deleted++
	}
	return report
}

func parallelDeviceOperation(
	ctx context.Context,
	cfg Config,
	operation func(context.Context, int) (int64, error),
) <-chan deviceOperationResult {
	results := make(chan deviceOperationResult, cfg.Concurrency)
	indices := make(chan int, cfg.Concurrency)
	workerCount := cfg.Concurrency
	if cfg.Devices < workerCount {
		workerCount = cfg.Devices
	}
	var workers sync.WaitGroup
	for worker := 0; worker < workerCount; worker++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for index := range indices {
				count, err := operation(ctx, index)
				results <- deviceOperationResult{index: index, count: count, err: err}
			}
		}()
	}
	go func() {
		for index := 0; index < cfg.Devices; index++ {
			indices <- index
		}
		close(indices)
		workers.Wait()
		close(results)
	}()
	return results
}

func ErrorClass(err error) string {
	if errors.Is(err, context.DeadlineExceeded) || strings.Contains(strings.ToLower(err.Error()), "deadline exceeded") {
		return "timeout"
	}
	if match := httpStatusPattern.FindStringSubmatch(err.Error()); len(match) == 2 {
		return "http-" + match[1]
	}
	lower := strings.ToLower(err.Error())
	if strings.Contains(lower, "response event id") {
		return "response-id-mismatch"
	}
	if errors.Is(err, context.Canceled) {
		return "cancelled"
	}
	if strings.Contains(lower, "dial ") || strings.Contains(lower, "connection") || strings.Contains(lower, "transport") {
		return "transport"
	}
	return "other"
}
