package driver

import (
	"context"
	"sync"
	"testing"
	"time"

	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces/mocks"
	sdkModels "github.com/edgexfoundry/device-sdk-go/v4/pkg/models"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestDriverPublishesAsyncValuesAndServesLatestReads(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 2)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()
	sdk.On("UpdateDeviceOperatingState", "arduino-001", models.OperatingState(models.Up)).Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	t.Cleanup(func() { require.NoError(t, driver.Stop(false)) })

	require.NoError(t, driver.AddDevice("arduino-001", testSerialProtocols(), models.AdminState(models.Unlocked)))
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)

	managed.options.OnState(models.OperatingState(models.Up))
	managed.options.OnSample(Sample{
		DeviceName: "arduino-001",
		SourceName: "acceleration",
		Readings: []Reading{
			{ResourceName: "acceleration_x_raw", Value: 336},
			{ResourceName: "acceleration_y_raw", Value: 288},
			{ResourceName: "acceleration_z_raw", Value: 292},
		},
	}, 987654321)

	event := <-asyncValues
	assert.Equal(t, "arduino-001", event.DeviceName)
	assert.Equal(t, "acceleration", event.SourceName)
	require.Len(t, event.CommandValues, 3)
	assert.Equal(t, "acceleration_x_raw", event.CommandValues[0].DeviceResourceName)
	assert.Equal(t, common.ValueTypeInt32, event.CommandValues[0].Type)
	assert.Equal(t, int32(336), event.CommandValues[0].Value)
	assert.Equal(t, int64(987654321), event.CommandValues[0].Origin)

	values, err := driver.HandleReadCommands("arduino-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "acceleration_z_raw", Type: common.ValueTypeInt32},
		{DeviceResourceName: "acceleration_x_raw", Type: common.ValueTypeInt32},
	})
	require.NoError(t, err)
	require.Len(t, values, 2)
	assert.Equal(t, "acceleration_z_raw", values[0].DeviceResourceName)
	assert.Equal(t, int32(292), values[0].Value)
	assert.Equal(t, int64(987654321), values[0].Origin)
	assert.Equal(t, "acceleration_x_raw", values[1].DeviceResourceName)
	assert.Equal(t, int32(336), values[1].Value)
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
	require.NoError(t, driver.AddDevice("arduino-001", testSerialProtocols(), models.AdminState(models.Unlocked)))

	_, err := driver.HandleReadCommands("arduino-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "temperature_raw", Type: common.ValueTypeInt32},
	})
	assert.ErrorContains(t, err, "no recent reading")

	_, err = driver.HandleReadCommands("arduino-001", testSerialProtocols(), []sdkModels.CommandRequest{
		{DeviceResourceName: "temperature_raw", Type: common.ValueTypeString},
	})
	assert.ErrorContains(t, err, "Int32")

	err = driver.HandleWriteCommands("arduino-001", testSerialProtocols(), nil, nil)
	assert.ErrorContains(t, err, "read-only")
}

func TestDriverValidatesDeviceIdentityAndSerialProperties(t *testing.T) {
	driver := NewDriver()

	valid := models.Device{Name: "arduino-001", Protocols: testSerialProtocols()}
	require.NoError(t, driver.ValidateDevice(valid))

	wrongIdentity := valid
	wrongIdentity.Name = "different-name"
	assert.ErrorContains(t, driver.ValidateDevice(wrongIdentity), "must match")

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
	sdk.On("Devices").Return([]models.Device{{
		Name:       "arduino-001",
		Protocols:  testSerialProtocols(),
		AdminState: models.AdminState(models.Unlocked),
	}}).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	require.NoError(t, driver.Start())
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)

	require.NoError(t, driver.UpdateDevice(
		"arduino-001",
		testSerialProtocols(),
		models.AdminState(models.Locked),
	))
	require.Eventually(t, managed.isClosed, time.Second, 5*time.Millisecond)
	require.NoError(t, driver.Stop(false))
}

func TestDriverRemoveStopsReaderAndDiscoveryIsUnsupported(t *testing.T) {
	asyncValues := make(chan *sdkModels.AsyncValues, 1)
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(true).Once()
	sdk.On("AsyncValuesChannel").Return(asyncValues).Once()
	sdk.On("LoggingClient").Return(nil).Once()

	factory := &recordingReaderFactory{}
	driver := newDriver(factory.create)
	require.NoError(t, driver.Initialize(sdk))
	require.NoError(t, driver.AddDevice("arduino-001", testSerialProtocols(), models.AdminState(models.Unlocked)))
	managed := factory.only(t)
	require.Eventually(t, managed.isRunning, time.Second, 5*time.Millisecond)

	require.NoError(t, driver.RemoveDevice("arduino-001", testSerialProtocols()))
	require.Eventually(t, managed.isClosed, time.Second, 5*time.Millisecond)
	assert.ErrorContains(t, driver.Discover(), "not supported")
	require.NoError(t, driver.Stop(false))
}

func TestDriverRequiresAsyncReadings(t *testing.T) {
	sdk := mocks.NewDeviceServiceSDK(t)
	sdk.On("AsyncReadingsEnabled").Return(false).Once()

	driver := NewDriver()
	assert.ErrorContains(t, driver.Initialize(sdk), "asynchronous readings")
}

func testSerialProtocols() map[string]models.ProtocolProperties {
	return map[string]models.ProtocolProperties{
		"serial": {
			"Port":     "/dev/arduino-001",
			"BaudRate": "115200",
			"DeviceID": "arduino-001",
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
