package driver

import (
	"context"
	"errors"
	"fmt"
	"sync"

	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces"
	sdkModels "github.com/edgexfoundry/device-sdk-go/v4/pkg/models"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/clients/logger"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
)

var _ interfaces.ProtocolDriver = (*Driver)(nil)

var supportedResources = map[string]struct{}{
	"temperature_raw":    {},
	"light_raw":          {},
	"magnetic_raw":       {},
	"acceleration_x_raw": {},
	"acceleration_y_raw": {},
	"acceleration_z_raw": {},
}

type managedReader interface {
	Run(ctx context.Context)
	Close() error
}

type readerFactory func(config SerialConfig, options ReaderOptions) managedReader

type latestReading struct {
	value  int32
	origin int64
}

type managedDevice struct {
	reader managedReader
	cancel context.CancelFunc
}

type Driver struct {
	mu        sync.RWMutex
	sdk       interfaces.DeviceServiceSDK
	logger    logger.LoggingClient
	async     chan *sdkModels.AsyncValues
	ctx       context.Context
	cancel    context.CancelFunc
	readers   map[string]*managedDevice
	latest    map[string]map[string]latestReading
	newReader readerFactory
	stopped   bool
}

func NewDriver() *Driver {
	return newDriver(func(config SerialConfig, options ReaderOptions) managedReader {
		return NewReader(config, options)
	})
}

func newDriver(factory readerFactory) *Driver {
	return &Driver{
		readers:   make(map[string]*managedDevice),
		latest:    make(map[string]map[string]latestReading),
		newReader: factory,
	}
}

func (driver *Driver) Initialize(sdk interfaces.DeviceServiceSDK) error {
	if sdk == nil {
		return errors.New("device service SDK is required")
	}
	if !sdk.AsyncReadingsEnabled() {
		return errors.New("asynchronous readings must be enabled")
	}
	async := sdk.AsyncValuesChannel()
	if async == nil {
		return errors.New("asynchronous readings channel is unavailable")
	}

	driver.mu.Lock()
	defer driver.mu.Unlock()
	if driver.sdk != nil {
		return errors.New("serial driver is already initialized")
	}
	driver.sdk = sdk
	driver.logger = sdk.LoggingClient()
	driver.async = async
	driver.ctx, driver.cancel = context.WithCancel(context.Background())
	return nil
}

func (driver *Driver) Start() error {
	driver.mu.RLock()
	sdk := driver.sdk
	driver.mu.RUnlock()
	if sdk == nil {
		return errors.New("serial driver is not initialized")
	}

	for _, device := range sdk.Devices() {
		if err := driver.UpdateDevice(device.Name, device.Protocols, device.AdminState); err != nil {
			return fmt.Errorf("start serial device %q: %w", device.Name, err)
		}
	}
	return nil
}

func (driver *Driver) Stop(force bool) error {
	driver.mu.Lock()
	if driver.stopped {
		driver.mu.Unlock()
		return nil
	}
	driver.stopped = true
	if driver.cancel != nil {
		driver.cancel()
	}
	managed := make([]*managedDevice, 0, len(driver.readers))
	for _, current := range driver.readers {
		managed = append(managed, current)
	}
	driver.readers = make(map[string]*managedDevice)
	driver.mu.Unlock()

	var closeErrors []error
	for _, current := range managed {
		current.cancel()
		if err := current.reader.Close(); err != nil {
			closeErrors = append(closeErrors, err)
		}
	}
	return errors.Join(closeErrors...)
}

func (driver *Driver) AddDevice(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
	adminState models.AdminState,
) error {
	return driver.UpdateDevice(deviceName, protocols, adminState)
}

func (driver *Driver) UpdateDevice(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
	adminState models.AdminState,
) error {
	if adminState == models.AdminState(models.Locked) {
		driver.stopDevice(deviceName, true)
		return nil
	}

	config, err := validateDeviceConfig(deviceName, protocols)
	if err != nil {
		return err
	}

	driver.mu.Lock()
	if driver.sdk == nil || driver.ctx == nil {
		driver.mu.Unlock()
		return errors.New("serial driver is not initialized")
	}
	if driver.stopped {
		driver.mu.Unlock()
		return errors.New("serial driver is stopped")
	}

	readerContext, cancel := context.WithCancel(driver.ctx)
	managed := &managedDevice{cancel: cancel}
	options := ReaderOptions{
		OnSample: func(sample Sample, origin int64) {
			driver.handleSample(deviceName, managed, sample, origin)
		},
		OnState: func(state models.OperatingState) {
			driver.handleState(deviceName, managed, state)
		},
		OnInvalidLine: func(err error) {
			driver.warn("discarding malformed serial telemetry for %s: %v", deviceName, err)
		},
	}
	managed.reader = driver.newReader(config, options)
	previous := driver.readers[deviceName]
	driver.readers[deviceName] = managed
	driver.mu.Unlock()

	if previous != nil {
		previous.cancel()
		if err := previous.reader.Close(); err != nil {
			driver.warn("close replaced serial reader for %s: %v", deviceName, err)
		}
	}
	go managed.reader.Run(readerContext)
	return nil
}

func (driver *Driver) RemoveDevice(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
) error {
	driver.stopDevice(deviceName, true)
	return nil
}

func (driver *Driver) HandleReadCommands(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
	requests []sdkModels.CommandRequest,
) ([]*sdkModels.CommandValue, error) {
	if len(requests) == 0 {
		return nil, errors.New("at least one read request is required")
	}

	driver.mu.RLock()
	deviceLatest := driver.latest[deviceName]
	values := make([]latestReading, len(requests))
	for index, request := range requests {
		if request.Type != common.ValueTypeInt32 {
			driver.mu.RUnlock()
			return nil, fmt.Errorf("resource %q must use %s", request.DeviceResourceName, common.ValueTypeInt32)
		}
		if _, ok := supportedResources[request.DeviceResourceName]; !ok {
			driver.mu.RUnlock()
			return nil, fmt.Errorf("unsupported serial resource %q", request.DeviceResourceName)
		}
		latest, ok := deviceLatest[request.DeviceResourceName]
		if !ok {
			driver.mu.RUnlock()
			return nil, fmt.Errorf("no recent reading for %s/%s", deviceName, request.DeviceResourceName)
		}
		values[index] = latest
	}
	driver.mu.RUnlock()

	result := make([]*sdkModels.CommandValue, len(requests))
	for index, request := range requests {
		commandValue, err := sdkModels.NewCommandValueWithOrigin(
			request.DeviceResourceName,
			common.ValueTypeInt32,
			values[index].value,
			values[index].origin,
		)
		if err != nil {
			return nil, fmt.Errorf("create command value for %q: %w", request.DeviceResourceName, err)
		}
		result[index] = commandValue
	}
	return result, nil
}

func (driver *Driver) HandleWriteCommands(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
	requests []sdkModels.CommandRequest,
	parameters []*sdkModels.CommandValue,
) error {
	return errors.New("Arduino serial device is read-only")
}

func (driver *Driver) Discover() error {
	return errors.New("serial device discovery is not supported")
}

func (driver *Driver) ValidateDevice(device models.Device) error {
	_, err := validateDeviceConfig(device.Name, device.Protocols)
	return err
}

func validateDeviceConfig(
	deviceName string,
	protocols map[string]models.ProtocolProperties,
) (SerialConfig, error) {
	config, err := ParseSerialConfig(protocols)
	if err != nil {
		return SerialConfig{}, err
	}
	if deviceName == "" {
		return SerialConfig{}, errors.New("EdgeX device name is required")
	}
	if config.DeviceID != deviceName {
		return SerialConfig{}, fmt.Errorf(
			"serial DeviceID %q must match EdgeX device name %q",
			config.DeviceID,
			deviceName,
		)
	}
	return config, nil
}

func (driver *Driver) handleSample(
	deviceName string,
	managed *managedDevice,
	sample Sample,
	origin int64,
) {
	if sample.DeviceName != deviceName {
		driver.warn("discarding serial telemetry with unexpected device %q for %s", sample.DeviceName, deviceName)
		return
	}

	commandValues := make([]*sdkModels.CommandValue, 0, len(sample.Readings))
	latest := make(map[string]latestReading, len(sample.Readings))
	for _, reading := range sample.Readings {
		if _, ok := supportedResources[reading.ResourceName]; !ok {
			driver.warn("discarding unsupported serial resource %q for %s", reading.ResourceName, deviceName)
			return
		}
		commandValue, err := sdkModels.NewCommandValueWithOrigin(
			reading.ResourceName,
			common.ValueTypeInt32,
			reading.Value,
			origin,
		)
		if err != nil {
			driver.warn("create async serial reading for %s/%s: %v", deviceName, reading.ResourceName, err)
			return
		}
		commandValues = append(commandValues, commandValue)
		latest[reading.ResourceName] = latestReading{value: reading.Value, origin: origin}
	}
	if len(commandValues) == 0 {
		return
	}

	driver.mu.Lock()
	if driver.readers[deviceName] != managed || driver.stopped {
		driver.mu.Unlock()
		return
	}
	if driver.latest[deviceName] == nil {
		driver.latest[deviceName] = make(map[string]latestReading)
	}
	for resourceName, reading := range latest {
		driver.latest[deviceName][resourceName] = reading
	}
	async := driver.async
	ctx := driver.ctx
	driver.mu.Unlock()

	event := &sdkModels.AsyncValues{
		DeviceName:    deviceName,
		SourceName:    sample.SourceName,
		CommandValues: commandValues,
	}
	select {
	case async <- event:
	case <-ctx.Done():
	}
}

func (driver *Driver) handleState(
	deviceName string,
	managed *managedDevice,
	state models.OperatingState,
) {
	driver.mu.RLock()
	active := driver.readers[deviceName] == managed && !driver.stopped
	sdk := driver.sdk
	driver.mu.RUnlock()
	if !active || sdk == nil {
		return
	}
	if err := sdk.UpdateDeviceOperatingState(deviceName, state); err != nil {
		driver.warn("update operating state for %s to %s: %v", deviceName, state, err)
	}
}

func (driver *Driver) stopDevice(deviceName string, clearLatest bool) {
	driver.mu.Lock()
	managed := driver.readers[deviceName]
	delete(driver.readers, deviceName)
	if clearLatest {
		delete(driver.latest, deviceName)
	}
	driver.mu.Unlock()
	if managed == nil {
		return
	}
	managed.cancel()
	if err := managed.reader.Close(); err != nil {
		driver.warn("close serial reader for %s: %v", deviceName, err)
	}
}

func (driver *Driver) warn(message string, args ...any) {
	driver.mu.RLock()
	loggingClient := driver.logger
	driver.mu.RUnlock()
	if loggingClient != nil {
		loggingClient.Warnf(message, args...)
	}
}
