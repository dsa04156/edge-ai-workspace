package driver

import (
	"context"
	"errors"
	"net/http"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces"
	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces/mocks"
	sdkModels "github.com/edgexfoundry/device-sdk-go/v4/pkg/models"
	bootstrapMocks "github.com/edgexfoundry/go-mod-bootstrap/v4/bootstrap/interfaces/mocks"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	gometrics "github.com/rcrowley/go-metrics"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
)

var testSenseHatDevices = map[string]string{
	"env-sensehat-temperature-01": "temperature",
	"env-sensehat-humidity-01":    "humidity",
	"env-sensehat-pressure-01":    "pressure",
	"imu-sensehat-compass-01":     "compass",
	"imu-sensehat-orientation-01": "orientation",
	"imu-sensehat-gyroscope-01":   "gyroscope",
}

type recordingSource struct {
	options SourceOptions
	mu      sync.Mutex
	running bool
	closed  bool
}

func (source *recordingSource) Run(ctx context.Context) {
	source.mu.Lock()
	source.running = true
	source.mu.Unlock()
	<-ctx.Done()
}

func (source *recordingSource) Close() error {
	source.mu.Lock()
	defer source.mu.Unlock()
	source.closed = true
	return nil
}

func (source *recordingSource) isRunning() bool {
	source.mu.Lock()
	defer source.mu.Unlock()
	return source.running
}

func (source *recordingSource) isClosed() bool {
	source.mu.Lock()
	defer source.mu.Unlock()
	return source.closed
}

type recordingSourceFactory struct {
	mu      sync.Mutex
	sources []*recordingSource
}

func (factory *recordingSourceFactory) create(_ I2CConfig, options SourceOptions) managedSource {
	factory.mu.Lock()
	defer factory.mu.Unlock()
	source := &recordingSource{options: options}
	factory.sources = append(factory.sources, source)
	return source
}

func (factory *recordingSourceFactory) only(t *testing.T) *recordingSource {
	t.Helper()
	factory.mu.Lock()
	defer factory.mu.Unlock()
	require.Len(t, factory.sources, 1)
	return factory.sources[0]
}

func testSenseHatSample() Sample {
	return Sample{
		DeviceID: "sensehat-001", Origin: 987654321,
		TempHumidity: 39.5, TempPressure: 36.5,
		Humidity: 35.25, Pressure: 1005.125, Compass: 345,
		Pitch: 358, Roll: 359, Yaw: 345,
		GyroX: 0.1, GyroY: 0.2, GyroZ: -0.3,
	}
}

func TestDriverPublishesSixGroupedEventsAndServesMultiResourceReads(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 6)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	for deviceName := range testSenseHatDevices {
		sdk.On("UpdateDeviceOperatingState", deviceName, models.OperatingState(models.Up)).Return(nil).Once()
	}

	factory := &recordingSourceFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })
	for deviceName, group := range testSenseHatDevices {
		require.NoError(t, driver.AddDevice(deviceName, testI2CProtocols(group), models.AdminState(models.Unlocked)))
	}
	source := factory.only(t)
	require.Eventually(t, source.isRunning, time.Second, 5*time.Millisecond)
	source.options.OnState(models.OperatingState(models.Up))
	source.options.OnSample(testSenseHatSample())

	events := make(map[string]*sdkModels.AsyncValues)
	for range 6 {
		event := <-asyncValues
		events[event.DeviceName] = event
	}
	require.Len(t, events, 6)
	assert.Equal(t, "temperature", events["env-sensehat-temperature-01"].SourceName)
	require.Len(t, events["env-sensehat-temperature-01"].CommandValues, 2)
	assert.Equal(t, "orientation", events["imu-sensehat-orientation-01"].SourceName)
	require.Len(t, events["imu-sensehat-orientation-01"].CommandValues, 3)
	for _, event := range events {
		for _, value := range event.CommandValues {
			assert.Equal(t, common.ValueTypeFloat64, value.Type)
			assert.Equal(t, int64(987654321), value.Origin)
		}
	}

	values, err := driver.HandleReadCommands(
		"imu-sensehat-orientation-01",
		testI2CProtocols("orientation"),
		[]sdkModels.CommandRequest{
			{DeviceResourceName: "pitch", Type: common.ValueTypeFloat64},
			{DeviceResourceName: "roll", Type: common.ValueTypeFloat64},
			{DeviceResourceName: "yaw", Type: common.ValueTypeFloat64},
		},
	)
	require.NoError(t, err)
	require.Len(t, values, 3)
	assert.Equal(t, []float64{358, 359, 345}, []float64{
		values[0].Value.(float64), values[1].Value.(float64), values[2].Value.(float64),
	})
}

func TestDriverStartsPreloadedDeviceAndClearsCacheWhenLocked(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("AddCustomRoute", latestRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).Return(nil).Once()
	sdk.On("AddCustomRoute", recentRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).Return(nil).Once()
	sdk.On("AddCustomRoute", statsRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).Return(nil).Once()
	sdk.On("Devices").Return([]models.Device{{
		Name:       "env-sensehat-humidity-01",
		Protocols:  testI2CProtocols("humidity"),
		AdminState: models.AdminState(models.Unlocked),
	}}).Once()

	factory := &recordingSourceFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	require.NoError(t, driver.Start())
	source := factory.only(t)
	require.Eventually(t, source.isRunning, time.Second, 5*time.Millisecond)
	source.options.OnSample(testSenseHatSample())
	<-asyncValues
	_, ok := driver.cache.latest("env-sensehat-humidity-01", "humidity", driver.now())
	require.True(t, ok)

	require.NoError(t, driver.UpdateDevice(
		"env-sensehat-humidity-01",
		testI2CProtocols("humidity"),
		models.AdminState(models.Locked),
	))
	require.Eventually(t, source.isClosed, time.Second, 5*time.Millisecond)
	_, ok = driver.cache.latest("env-sensehat-humidity-01", "humidity", driver.now())
	assert.False(t, ok)
	require.NoError(t, driver.Stop(false))
}

func TestDriverRejectsInvalidReadWriteAndPreservesUnchangedBinding(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	factory := &recordingSourceFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })
	require.NoError(t, driver.AddDevice("env-sensehat-humidity-01", testI2CProtocols("humidity"), models.AdminState(models.Unlocked)))
	source := factory.only(t)
	source.options.OnSample(testSenseHatSample())
	<-asyncValues

	require.NoError(t, driver.UpdateDevice("env-sensehat-humidity-01", testI2CProtocols("humidity"), models.AdminState(models.Unlocked)))
	assert.False(t, source.isClosed())
	_, ok := driver.cache.latest("env-sensehat-humidity-01", "humidity", driver.now())
	assert.True(t, ok)

	_, err := driver.HandleReadCommands("env-sensehat-humidity-01", testI2CProtocols("humidity"), []sdkModels.CommandRequest{{DeviceResourceName: "pressure", Type: common.ValueTypeFloat64}})
	assert.ErrorContains(t, err, "not part of")
	_, err = driver.HandleReadCommands("env-sensehat-humidity-01", testI2CProtocols("humidity"), []sdkModels.CommandRequest{{DeviceResourceName: "humidity", Type: common.ValueTypeString}})
	assert.ErrorContains(t, err, "Float64")
	assert.ErrorContains(t, driver.HandleWriteCommands("env-sensehat-humidity-01", nil, nil, nil), "read-only")
	assert.ErrorContains(t, driver.Discover(), "not supported")

	devices := make([]string, 0, len(testSenseHatDevices))
	for name := range testSenseHatDevices {
		devices = append(devices, name)
	}
	sort.Strings(devices)
	assert.Len(t, devices, 6)
}

func TestDriverRequiresAsyncReadingsAndReportsRouteFailure(t *testing.T) {
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(false).Once()
	assert.ErrorContains(t, NewDriver().Initialize(sdk), "asynchronous readings")

	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk2 := newTestDeviceServiceSDK(t)
	sdk2.On("AsyncReadingsEnabled").Return(true).Once()
	sdk2.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk2.On("LoggingClient").Return(nil).Once()
	sdk2.On("AddCustomRoute", latestRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).Return(errors.New("route unavailable")).Once()
	driver := newDriver((&recordingSourceFactory{}).create)
	require.NoError(t, driver.Initialize(sdk2))
	assert.ErrorContains(t, driver.Start(), "register local latest route")
	require.NoError(t, driver.Stop(false))
}

func TestDriverUsesConfiguredCacheAndRegistersMetrics(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("DriverConfigs").Return(map[string]string{
		localDataCacheMaxAgeConfig:     "30s",
		localDataCacheMaxSamplesConfig: "2",
		localDataCacheMaxBytesConfig:   "4096",
	}).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	manager := bootstrapMocks.NewMetricsManager(t)
	registered := make(map[string]interface{})
	for _, name := range []string{
		localDataCacheSamplesMetric,
		localDataCacheSeriesMetric,
		localDataCacheAllocatedBytesMetric,
		localDataCacheEvictionsMetric,
	} {
		metricName := name
		manager.On("Register", metricName, mock.Anything, mock.Anything).
			Run(func(arguments mock.Arguments) {
				registered[metricName] = arguments.Get(1)
			}).
			Return(nil).
			Once()
	}
	sdk.On("MetricsManager").Return(manager).Once()

	driver := newDriver((&recordingSourceFactory{}).create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	stats := driver.cache.stats()
	assert.Equal(t, 30*time.Second, stats.MaxAge)
	assert.Equal(t, 2, stats.MaxSamplesPerSeries)
	assert.Equal(t, int64(4096), stats.MaxBytes)

	for origin := int64(1); origin <= 3; origin++ {
		driver.cache.append("device", "humidity", floatSample(origin, float64(origin)))
	}
	assert.Equal(t, int64(2), registered[localDataCacheSamplesMetric].(gometrics.Gauge).Value())
	assert.Equal(t, int64(1), registered[localDataCacheSeriesMetric].(gometrics.Gauge).Value())
	assert.Positive(t, registered[localDataCacheAllocatedBytesMetric].(gometrics.Gauge).Value())
	assert.Equal(t, int64(1), registered[localDataCacheEvictionsMetric].(gometrics.Counter).Count())
}

func newTestDeviceServiceSDK(t *testing.T) *mocks.DeviceServiceSDK {
	t.Helper()
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("DriverConfigs").Return(map[string]string{}).Maybe()
	sdk.On("MetricsManager").Return(nil).Maybe()
	return sdk
}
