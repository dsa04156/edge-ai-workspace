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
	bootstrapMocks "github.com/edgexfoundry/go-mod-bootstrap/v4/bootstrap/interfaces/mocks"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	gometrics "github.com/rcrowley/go-metrics"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
)

func TestDriverPublishesRoutedAsyncValuesAndServesLatestReads(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := newTestDeviceServiceSDK(t)
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

func TestDriverPublishesAndCachesMPU6050Float64Readings(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 8)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 987654321 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	protocols := testMPU6050Protocols("*")
	require.NoError(t, driver.AddDevice(
		"mpu6050-imu-001",
		protocols,
		models.AdminState(models.Unlocked),
	))
	managed := factory.only(t)
	require.Equal(t, mpu6050SerialParser, managed.config.Parser)

	acceleration := 9.80665
	gyro := -0.0125
	managed.options.OnSample(Sample{
		DeviceName: "mpu6050-001",
		SourceName: "imu",
		Readings: []Reading{
			{ResourceName: "acceleration_z", FloatValue: &acceleration},
			{ResourceName: "gyro_y", FloatValue: &gyro},
		},
	}, 987654321)

	events := map[string]*sdkModels.AsyncValues{}
	for range 2 {
		event := <-asyncValues
		events[event.CommandValues[0].DeviceResourceName] = event
	}
	for resourceName, expected := range map[string]float64{
		"acceleration_z": acceleration,
		"gyro_y":         gyro,
	} {
		event := events[resourceName]
		require.NotNil(t, event)
		assert.Equal(t, "mpu6050-imu-001", event.DeviceName)
		assert.Equal(t, resourceName, event.SourceName)
		require.Len(t, event.CommandValues, 1)
		assert.Equal(t, common.ValueTypeFloat64, event.CommandValues[0].Type)
		assert.InDelta(t, expected, event.CommandValues[0].Value, 0.000001)
	}

	values, err := driver.HandleReadCommands(
		"mpu6050-imu-001",
		protocols,
		[]sdkModels.CommandRequest{{
			DeviceResourceName: "acceleration_z",
			Type:               common.ValueTypeFloat64,
		}},
	)
	require.NoError(t, err)
	require.Len(t, values, 1)
	assert.Equal(t, common.ValueTypeFloat64, values[0].Type)
	assert.InDelta(t, acceleration, values[0].Value, 0.000001)

	cached, ok := driver.cache.latest(
		"mpu6050-imu-001",
		"acceleration_z",
		driver.now(),
	)
	require.True(t, ok)
	assert.Equal(t, common.ValueTypeFloat64, cached.ValueType)
	assert.InDelta(t, acceleration, cached.Value, 0.000001)
}

func TestDriverRejectsReadBeforeFirstSampleAndAllWrites(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("AddCustomRoute", latestRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
		Return(nil).
		Once()
	sdk.On("AddCustomRoute", recentRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
		Return(nil).
		Once()
	sdk.On("AddCustomRoute", statsRoute, interfaces.Unauthenticated, mock.Anything, http.MethodGet).
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
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(false).Once()

	driver := NewDriver()
	assert.ErrorContains(t, driver.Initialize(sdk), "asynchronous readings")
}

func TestDriverSharesOneReaderAndFansOutAcceleration(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 3)
	sdk := newTestDeviceServiceSDK(t)
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

func TestDriverRoutesAllResourcesToOneAggregatePhysicalDevice(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 8)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 123456789 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice(
		"arduino-multisensor-001",
		testSerialProtocols("*"),
		models.AdminState(models.Unlocked),
	))
	assert.Equal(t, 1, factory.count())

	factory.only(t).options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "acceleration",
		Readings: []Reading{
			{ResourceName: "acceleration_x_raw", Value: 301},
			{ResourceName: "acceleration_y_raw", Value: 302},
			{ResourceName: "acceleration_z_raw", Value: 303},
		},
	}, 123456789)

	observed := make(map[string]*sdkModels.AsyncValues)
	for range 3 {
		event := <-asyncValues
		assert.Equal(t, "arduino-multisensor-001", event.DeviceName)
		require.Len(t, event.CommandValues, 1)
		observed[event.CommandValues[0].DeviceResourceName] = event
	}
	assert.Len(t, observed, 3)

	values, err := driver.HandleReadCommands(
		"arduino-multisensor-001",
		testSerialProtocols("*"),
		[]sdkModels.CommandRequest{
			{
				DeviceResourceName: "acceleration_x_raw",
				Type:               common.ValueTypeInt32,
			},
			{
				DeviceResourceName: "acceleration_z_raw",
				Type:               common.ValueTypeInt32,
			},
		},
	)
	require.NoError(t, err)
	require.Len(t, values, 2)
	assert.Equal(t, int32(301), values[0].Value)
	assert.Equal(t, int32(303), values[1].Value)
}

func TestDriverFansOutToAggregateAndLegacyDeviceDuringMigration(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 4)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	driver.now = func() int64 { return 123456789 }
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocols("temperature_raw"),
		models.AdminState(models.Unlocked),
	))
	require.NoError(t, driver.AddDevice(
		"arduino-multisensor-001",
		testSerialProtocols("*"),
		models.AdminState(models.Unlocked),
	))
	assert.Equal(t, 1, factory.count())

	factory.only(t).options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 321},
		},
	}, 123456789)

	observed := map[string]bool{}
	for range 2 {
		observed[(<-asyncValues).DeviceName] = true
	}
	assert.Equal(t, map[string]bool{
		"virtual-temperature-001": true,
		"arduino-multisensor-001": true,
	}, observed)
}

func TestDriverUsesIndependentReadersForTwoSerialConnections(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := newTestDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice(
		"virtual-temperature-001",
		testSerialProtocolsFor(
			"/dev/arduino-001",
			115200,
			"arduino-001",
			"temperature_raw",
		),
		models.AdminState(models.Unlocked),
	))
	require.NoError(t, driver.AddDevice(
		"virtual-light-002",
		testSerialProtocolsFor(
			"/dev/arduino-002",
			57600,
			"arduino-002",
			"light_raw",
		),
		models.AdminState(models.Unlocked),
	))

	assert.Equal(t, 2, factory.count())
	first := factory.forPort(t, "/dev/arduino-001")
	second := factory.forPort(t, "/dev/arduino-002")
	require.Eventually(t, first.isRunning, time.Second, 5*time.Millisecond)
	require.Eventually(t, second.isRunning, time.Second, 5*time.Millisecond)
	assert.Equal(t, 115200, first.config.BaudRate)
	assert.Equal(t, 57600, second.config.BaudRate)

	first.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "temperature",
		Readings: []Reading{
			{ResourceName: "temperature_raw", Value: 336},
		},
	}, 987654321)
	second.options.OnSample(Sample{
		DeviceName: "arduino-002",
		SourceName: "light",
		Readings: []Reading{
			{ResourceName: "light_raw", Value: 512},
		},
	}, 987654322)

	events := make(map[string]*sdkModels.AsyncValues, 2)
	for range 2 {
		event := <-asyncValues
		events[event.DeviceName] = event
	}
	assert.Equal(t, int32(336), events["virtual-temperature-001"].CommandValues[0].Value)
	assert.Equal(t, int32(512), events["virtual-light-002"].CommandValues[0].Value)
}

func TestDriverFansOutConnectionStateAndClosesAfterLastRoute(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
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
	sdk := newTestDeviceServiceSDK(t)
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

	driver := newDriver((&recordingReaderFactory{}).create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	stats := driver.cache.stats()
	assert.Equal(t, 30*time.Second, stats.MaxAge)
	assert.Equal(t, 2, stats.MaxSamplesPerSeries)
	assert.Equal(t, int64(4096), stats.MaxBytes)

	for origin := int64(1); origin <= 3; origin++ {
		driver.cache.append("device", "resource", cachedSample{
			Origin:    origin,
			ValueType: common.ValueTypeInt32,
			Value:     int32(origin),
		})
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

func testSerialProtocols(resourceNames ...string) map[string]models.ProtocolProperties {
	resourceName := "temperature_raw"
	if len(resourceNames) > 0 {
		resourceName = resourceNames[0]
	}
	return testSerialProtocolsFor(
		"/dev/arduino-001",
		115200,
		"arduino-001",
		resourceName,
	)
}

func testSerialProtocolsFor(
	port string,
	baudRate int,
	deviceID string,
	resourceName string,
) map[string]models.ProtocolProperties {
	return map[string]models.ProtocolProperties{
		"serial": {
			"Port":         port,
			"BaudRate":     baudRate,
			"DeviceID":     deviceID,
			"ResourceName": resourceName,
		},
	}
}

func testMPU6050Protocols(resourceName string) map[string]models.ProtocolProperties {
	return map[string]models.ProtocolProperties{
		"serial": {
			"Port":         "/dev/mpu6050-001",
			"BaudRate":     115200,
			"DeviceID":     "mpu6050-001",
			"Parser":       mpu6050SerialParser,
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

func (factory *recordingReaderFactory) forPort(t *testing.T, port string) *fakeManagedReader {
	t.Helper()
	factory.mu.Lock()
	defer factory.mu.Unlock()
	for _, reader := range factory.readers {
		if reader.config.Port == port {
			return reader
		}
	}
	require.FailNow(t, "serial reader not found", "port=%s", port)
	return nil
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
