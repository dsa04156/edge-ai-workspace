package driver

import (
	"context"
	"errors"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces"
	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces/mocks"
	sdkModels "github.com/edgexfoundry/device-sdk-go/v4/pkg/models"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
)

func TestDriverPublishesRoutedAsyncValuesAndServesLatestReads(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "virtual-temperature-001", models.OperatingState(models.Up)).Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice("virtual-temperature-001", testSerialProtocols(), models.AdminState(models.Unlocked)))
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)

	managed.options.OnState(models.OperatingState(models.Up))
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 336},
		},
	}, 987654321)

	event := <-asyncValues
	assert.Equal(t, "virtual-temperature-001", event.DeviceName)
	assert.Equal(t, "temperature", event.SourceName)
	require.Len(t, event.CommandValues, 1)
	assert.Equal(t, "temperature_raw", event.CommandValues[0].DeviceResourceName)
	assert.Equal(t, common.ValueTypeInt32, event.CommandValues[0].Type)
	assert.Equal(t, int32(336), event.CommandValues[0].Value)
	assert.Equal(t, int64(987654321), event.CommandValues[0].Origin)

	values, err := driver.HandleReadCommands("virtual-temperature-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "temperature_raw", Type: common.ValueTypeInt32},
	})
	require.NoError(t, err)
	require.Len(t, values, 1)
	assert.Equal(t, "temperature_raw", values[0].DeviceResourceName)
	assert.Equal(t, int32(336), values[0].Value)
	assert.Equal(t, int64(987654321), values[0].Origin)

	cached, ok := driver.cache.latest(
		"virtual-temperature-001",
		"temperature_raw",
		driver.now(),
	)
	require.True(t, ok)
	assert.Equal(t, int32(336), cached.Value)
	assert.Equal(t, int64(987654321), cached.Origin)
}

func TestDriverRejectsReadBeforeFirstSampleAndAllWrites(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	driver := newDriver((&recordingReaderFactory{}).create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })
	require.NoError(t, driver.AddDevice("virtual-temperature-001", testSerialProtocols(), models.AdminState(models.Unlocked)))

	_, err := driver.HandleReadCommands("virtual-temperature-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "temperature_raw", Type: common.ValueTypeInt32},
	})
	assert.ErrorContains(t, err, "no recent reading")

	_, err = driver.HandleReadCommands("virtual-temperature-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "temperature_raw", Type: common.ValueTypeString},
	})
	assert.ErrorContains(t, err, "Int32")

	err = driver.HandleWriteCommands("virtual-temperature-001", testSerialProtocols(), nil, nil)
	assert.ErrorContains(t, err, "read-only")
}

func TestDriverValidatesDeviceIdentityAndSerialProperties(t *testing.T) {
	driver := NewDriver()

	valid := models.Device{Name: "virtual-temperature-001", Protocols: testSerialProtocols()}
	require.NoError(t, driver.ValidateDevice(valid))

	emptyIdentity := valid
	emptyIdentity.Name = ""
	assert.ErrorContains(t, driver.ValidateDevice(emptyIdentity), "name is required")

	badPort := valid
	badPort.Protocols = testSerialProtocols()
	badPort.Protocols["serial"]["Port"] = "ttyACM0"
	assert.Error(t, driver.ValidateDevice(badPort))
}

func TestDriverStartsExistingDeviceAndStopsItWhenLocked(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("AddCustomRoute", latestRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
		Return(nil).
		Once()
	sdk.On("AddCustomRoute", recentRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
		Return(nil).
		Once()
	sdk.On("Devices").Return([]models.Device{{
		Name:       "virtual-temperature-001",
		Protocols:  testSerialProtocols(),
		AdminState: models.AdminState(models.Unlocked),
	}}).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	require.NoError(t, driver.Start())
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 336},
		},
	}, 987654321)
	<-asyncValues
	_, ok := driver.cache.latest("virtual-temperature-001", "temperature_raw", driver.now())
	require.True(t, ok)

	require.NoError(t, driver.UpdateDevice(
		"virtual-temperature-001",
		testSerialProtocols(),
		models.AdminState(models.Locked),
	))
	require.Eventually(t, managed.isClosed, time.Second, 5*time.Millisecond)
	_, ok = driver.cache.latest("virtual-temperature-001", "temperature_raw", driver.now())
	assert.False(t, ok)
	require.NoError(t, driver.Stop(false))
}

func TestDriverStartFailsWhenLocalDataRouteCannotRegister(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("AddCustomRoute", latestRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
		Return(errors.New("route unavailable")).
		Once()

	driver := newDriver((&recordingReaderFactory{}).create)
	require.NoError(t, driver.Initialize(sdk))
	assert.ErrorContains(t, driver.Start(), "register local latest route")
	require.NoError(t, driver.Stop(false))
}

func TestDriverDoesNotRestartReaderForUnchangedMetadataUpdate(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })
	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocols(),
		models.AdminState(models.Unlocked),
	))
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 336},
		},
	}, 987654321)
	<-asyncValues

	require.NoError(t, driver.UpdateDevice(
		"virtual-temperature-001",
		testSerialProtocols(),
		models.AdminState(models.Unlocked),
	))

	assert.Equal(t, 1, factory.count())
	assert.False(t, managed.isClosed())
	cached, ok := driver.cache.latest("virtual-temperature-001", "temperature_raw", driver.now())
	require.True(t, ok)
	assert.Equal(t, int32(336), cached.Value)
}

func TestDriverRemoveStopsReaderAndDiscoveryIsUnsupported(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	require.NoError(t, driver.AddDevice("virtual-temperature-001", testSerialProtocols(), models.AdminState(models.Unlocked)))
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 336},
		},
	}, 987654321)
	<-asyncValues
	_, ok := driver.cache.latest("virtual-temperature-001", "temperature_raw", driver.now())
	require.True(t, ok)

	require.NoError(t, driver.RemoveDevice("virtual-temperature-001", testSerialProtocols()))
	require.Eventually(t, managed.isClosed, time.Second, 5*time.Millisecond)
	_, ok = driver.cache.latest("virtual-temperature-001", "temperature_raw", driver.now())
	assert.False(t, ok)
	assert.ErrorContains(t, driver.Discover(), "not supported")
	require.NoError(t, driver.Stop(false))
}

func TestDriverRequiresAsyncReadings(t *testing.T) {
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(false).Once()

	driver := NewDriver()
	assert.ErrorContains(t, driver.Initialize(sdk), "asynchronous readings")
}

func TestDriverSharesOneReaderAndFansOutAcceleration(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 3)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	devices := []struct {
		name     string
		resource string
	}{
		{name: "virtual-acceleration-x-001", resource: "acceleration_x_raw"},
		{name: "virtual-acceleration-y-001", resource: "acceleration_y_raw"},
		{name: "virtual-acceleration-z-001", resource: "acceleration_z_raw"},
	}
	for _, device := range devices {
		require.NoError(t, driver.AddDevice(
			device.name,
			testSerialProtocols(device.resource),
			models.AdminState(models.Unlocked),
		))
	}

	assert.Equal(t, 1, factory.count())
	managed := factory.only(t)
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "acceleration",
		Readings: []Reading{
			{ResourceName: "acceleration_x_raw", Value: 336},
			{ResourceName: "acceleration_y_raw", Value: 288},
			{ResourceName: "acceleration_z_raw", Value: 292},
		},
	}, 987654321)

	events := make(map[string]*sdkModels.AsyncValues, len(devices))
	for range devices {
		event := <-asyncValues
		events[event.DeviceName] = event
	}
	for _, device := range devices {
		event := events[device.name]
		require.NotNil(t, event)
		assert.Equal(t, device.resource[:len(device.resource)-4], event.SourceName)
		require.Len(t, event.CommandValues, 1)
		assert.Equal(t, device.resource, event.CommandValues[0].DeviceResourceName)
		assert.Equal(t, int64(987654321), event.CommandValues[0].Origin)
	}

	values, err := driver.HandleReadCommands(
		"virtual-acceleration-z-001",
		testSerialProtocols("acceleration_z_raw"),
		[]sdkModels.CommandRequest{{
			DeviceResourceName: "acceleration_z_raw",
			Type:               common.ValueTypeInt32,
		}},
	)
	require.NoError(t, err)
	require.Len(t, values, 1)
	assert.Equal(t, int32(292), values[0].Value)

	for _, device := range devices {
		samples := driver.cache.query(
			device.name,
			device.resource,
			987654321,
			987654321,
			10,
			driver.now(),
		)
		require.Len(t, samples, 1)
		assert.Equal(t, int64(987654321), samples[0].Origin)
	}
}

func TestDriverFansOutConnectionStateAndClosesAfterLastRoute(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "virtual-temperature-001", models.OperatingState(models.Up)).Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "virtual-light-001", models.OperatingState(models.Up)).Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))

	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocols("temperature_raw"),
		models.AdminState(models.Unlocked),
	))
	require.NoError(t, driver.AddDevice(
		"virtual-light-001",
		testSerialProtocols("light_raw"),
		models.AdminState(models.Unlocked),
	))
	managed := factory.only(t)
	managed.options.OnState(models.OperatingState(models.Up))

	require.NoError(t, driver.RemoveDevice(
		"virtual-temperature-001",
		testSerialProtocols("temperature_raw"),
	))
	assert.False(t, managed.isClosed())
	require.NoError(t, driver.RemoveDevice(
		"virtual-light-001",
		testSerialProtocols("light_raw"),
	))
	require.Eventually(t, managed.isClosed, time.Second, 5*time.Millisecond)
	require.NoError(t, driver.Stop(false))
}

func TestDriverAppliesKnownConnectionStateToNewRoute(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "virtual-temperature-001", models.OperatingState(models.Up)).Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "virtual-light-001", models.OperatingState(models.Up)).Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocols("temperature_raw"),
		models.AdminState(models.Unlocked),
	))
	managed := factory.only(t)
	managed.options.OnState(models.OperatingState(models.Up))

	require.NoError(t, driver.AddDevice(
		"virtual-light-001",
		testSerialProtocols("light_raw"),
		models.AdminState(models.Unlocked),
	))
	assert.Equal(t, 1, factory.count())
}

func TestDriverRejectsDuplicateResourceBinding(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })
	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocols("temperature_raw"),
		models.AdminState(models.Unlocked),
	))

	err := driver.AddDevice(
		"virtual-temperature-duplicate",
		testSerialProtocols("temperature_raw"),
		models.AdminState(models.Unlocked),
	)
	assert.ErrorContains(t, err, "already routed")
	assert.Equal(t, 1, factory.count())
}

func testSerialProtocols(resourceNames ...string) map[string]models.ProtocolProperties {
	resourceName := "temperature_raw"
	if len(resourceNames) > 0 {
		resourceName = resourceNames[0]
	}
	return map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/arduino-001",
			"BaudRate":     "115200",
			"DeviceID":     "arduino-001",
			"ResourceName": resourceName,
		},
	}
}

type recordingReaderFactory struct {
	mu      sync.Mutex
	readers []*fakeManagedReader
}

func (factory *recordingReaderFactory) create(config SerialConfig, options ReaderOptions) managedReader {
	reader := &fakeManagedReader{
		config:  config,
		options: options,
		running: make(chan struct{}),
		closed:  make(chan struct{}),
	}
	factory.mu.Lock()
	factory.readers = append(factory.readers, reader)
	factory.mu.Unlock()
	return reader
}

func (factory *recordingReaderFactory) only(t *testing.T) *fakeManagedReader {
	t.Helper()
	factory.mu.Lock()
	defer factory.mu.Unlock()
	require.Len(t, factory.readers, 1)
	return factory.readers[0]
}

func (factory *recordingReaderFactory) count() int {
	factory.mu.Lock()
	defer factory.mu.Unlock()
	return len(factory.readers)
}

type fakeManagedReader struct {
	config    SerialConfig
	options   ReaderOptions
	running   chan struct{}
	closed    chan struct{}
	runOnce   sync.Once
	closeOnce sync.Once
}

func (reader *fakeManagedReader) Run(ctx context.Context) {
	reader.runOnce.Do(func() { close(reader.running) })
	select {
	case <-ctx.Done():
	case <-reader.closed:
	}
}

func (reader *fakeManagedReader) Close() error {
	reader.closeOnce.Do(func() { close(reader.closed) })
	return nil
}

func (reader *fakeManagedReader) isRunning() bool {
	select {
	case <-reader.running:
		return true
	default:
		return false
	}
}

func (reader *fakeManagedReader) isClosed() bool {
	select {
	case <-reader.closed:
		return true
	default:
		return false
	}
}
