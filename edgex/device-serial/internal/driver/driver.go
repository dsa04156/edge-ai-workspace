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

var sourceNames = map[string]string{
	"temperature_raw":    "temperature",
	"light_raw":          "light",
	"magnetic_raw":       "magnetic",
	"acceleration_x_raw": "acceleration_x",
	"acceleration_y_raw": "acceleration_y",
	"acceleration_z_raw": "acceleration_z",
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

type managedConnection struct {
	reader   managedReader
	cancel   context.CancelFunc
	config   SerialConfig
	routes   map[string]string
	state    models.OperatingState
	hasState bool
}

type deviceBinding struct {
	config     SerialConfig
	connection *managedConnection
}

type Driver struct {
	mu          sync.RWMutex
	sdk         interfaces.DeviceServiceSDK
	logger      logger.LoggingClient
	async       chan *sdkModels.AsyncValues
	ctx         context.Context
	cancel      context.CancelFunc
	connections map[connectionKey]*managedConnection
	bindings    map[string]*deviceBinding
	latest      map[string]map[string]latestReading
	newReader   readerFactory
	stopped     bool
}

func NewDriver() *Driver {
	return newDriver(func(config SerialConfig, options ReaderOptions) managedReader {
		return NewReader(config, options)
	})
}

func newDriver(factory readerFactory) *Driver {
	return &Driver{
		connections: make(map[connectionKey]*managedConnection),
		bindings:    make(map[string]*deviceBinding),
		latest:      make(map[string]map[string]latestReading),
		newReader:   factory,
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
	managed := make([]*managedConnection, 0, len(driver.connections))
	for _, current := range driver.connections {
		managed = append(managed, current)
	}
	driver.connections = make(map[connectionKey]*managedConnection)
	driver.bindings = make(map[string]*deviceBinding)
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

	var obsolete *managedConnection
	var created *managedConnection
	var readerContext context.Context
	var readerCancel context.CancelFunc
	var knownState *models.OperatingState
	var sdk interfaces.DeviceServiceSDK

	driver.mu.Lock()
	if driver.sdk == nil || driver.ctx == nil {
		driver.mu.Unlock()
		return errors.New("serial driver is not initialized")
	}
	if driver.stopped {
		driver.mu.Unlock()
		return errors.New("serial driver is stopped")
	}
	if current := driver.bindings[deviceName]; current != nil && current.config == config {
		driver.mu.Unlock()
		return nil
	}

	key := config.key()
	target := driver.connections[key]
	if target != nil {
		if routedDevice, ok := target.routes[config.ResourceName]; ok && routedDevice != deviceName {
			driver.mu.Unlock()
			return fmt.Errorf(
				"serial resource %q is already routed to %q",
				config.ResourceName,
				routedDevice,
			)
		}
	}

	current := driver.bindings[deviceName]
	if current != nil {
		delete(current.connection.routes, current.config.ResourceName)
		delete(driver.bindings, deviceName)
		delete(driver.latest, deviceName)
		if len(current.connection.routes) == 0 && current.connection != target {
			delete(driver.connections, current.config.key())
			obsolete = current.connection
		}
	}

	if target == nil {
		readerContext, readerCancel = context.WithCancel(driver.ctx)
		target = &managedConnection{
			cancel: readerCancel,
			config: config,
			routes: make(map[string]string),
		}
		options := ReaderOptions{
			OnSample: func(sample Sample, origin int64) {
				driver.handleSample(target, sample, origin)
			},
			OnState: func(state models.OperatingState) {
				driver.handleState(target, state)
			},
			OnInvalidLine: func(err error) {
				driver.warn("discarding malformed serial telemetry for %s: %v", config.DeviceID, err)
			},
		}
		target.reader = driver.newReader(config, options)
		driver.connections[key] = target
		created = target
	}
	target.routes[config.ResourceName] = deviceName
	driver.bindings[deviceName] = &deviceBinding{config: config, connection: target}
	delete(driver.latest, deviceName)
	if target.hasState {
		state := target.state
		knownState = &state
	}
	sdk = driver.sdk
	driver.mu.Unlock()

	if obsolete != nil {
		obsolete.cancel()
		if err := obsolete.reader.Close(); err != nil {
			driver.warn("close unused serial reader for %s: %v", obsolete.config.DeviceID, err)
		}
	}
	if created != nil {
		go created.reader.Run(readerContext)
	}
	if knownState != nil {
		if err := sdk.UpdateDeviceOperatingState(deviceName, *knownState); err != nil {
			driver.warn("update operating state for %s to %s: %v", deviceName, *knownState, err)
		}
	}
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
	return config, nil
}

func (driver *Driver) handleSample(
	managed *managedConnection,
	sample Sample,
	origin int64,
) {
	if sample.DeviceName != managed.config.DeviceID {
		driver.warn(
			"discarding serial telemetry with unexpected physical device %q for %s",
			sample.DeviceName,
			managed.config.DeviceID,
		)
		return
	}

	type routedEvent struct {
		deviceName string
		sourceName string
		value      *sdkModels.CommandValue
	}
	events := make([]routedEvent, 0, len(sample.Readings))

	driver.mu.Lock()
	if driver.connections[managed.config.key()] != managed || driver.stopped {
		driver.mu.Unlock()
		return
	}
	for _, reading := range sample.Readings {
		if _, ok := supportedResources[reading.ResourceName]; !ok {
			continue
		}
		deviceName, ok := managed.routes[reading.ResourceName]
		if !ok {
			continue
		}
		sourceName, ok := sourceNames[reading.ResourceName]
		if !ok {
			continue
		}
		commandValue, err := sdkModels.NewCommandValueWithOrigin(
			reading.ResourceName,
			common.ValueTypeInt32,
			reading.Value,
			origin,
		)
		if err != nil {
			driver.mu.Unlock()
			driver.warn("create async serial reading for %s/%s: %v", deviceName, reading.ResourceName, err)
			return
		}
		if driver.latest[deviceName] == nil {
			driver.latest[deviceName] = make(map[string]latestReading)
		}
		driver.latest[deviceName][reading.ResourceName] = latestReading{
			value:  reading.Value,
			origin: origin,
		}
		events = append(events, routedEvent{
			deviceName: deviceName,
			sourceName: sourceName,
			value:      commandValue,
		})
	}
	async := driver.async
	ctx := driver.ctx
	driver.mu.Unlock()

	for _, routed := range events {
		event := &sdkModels.AsyncValues{
			DeviceName:    routed.deviceName,
			SourceName:    routed.sourceName,
			CommandValues: []*sdkModels.CommandValue{routed.value},
		}
		select {
		case async <- event:
		case <-ctx.Done():
			return
		}
	}
}

func (driver *Driver) handleState(
	managed *managedConnection,
	state models.OperatingState,
) {
	driver.mu.Lock()
	active := driver.connections[managed.config.key()] == managed && !driver.stopped
	sdk := driver.sdk
	if active {
		managed.state = state
		managed.hasState = true
	}
	deviceSet := make(map[string]struct{}, len(managed.routes))
	if active {
		for _, deviceName := range managed.routes {
			deviceSet[deviceName] = struct{}{}
		}
	}
	driver.mu.Unlock()
	if !active || sdk == nil {
		return
	}
	for deviceName := range deviceSet {
		if err := sdk.UpdateDeviceOperatingState(deviceName, state); err != nil {
			driver.warn("update operating state for %s to %s: %v", deviceName, state, err)
		}
	}
}

func (driver *Driver) stopDevice(deviceName string, clearLatest bool) {
	driver.mu.Lock()
	binding := driver.bindings[deviceName]
	var unused *managedConnection
	if binding != nil {
		delete(binding.connection.routes, binding.config.ResourceName)
		delete(driver.bindings, deviceName)
		if len(binding.connection.routes) == 0 {
			delete(driver.connections, binding.config.key())
			unused = binding.connection
		}
	}
	if clearLatest {
		delete(driver.latest, deviceName)
	}
	driver.mu.Unlock()
	if unused == nil {
		return
	}
	unused.cancel()
	if err := unused.reader.Close(); err != nil {
		driver.warn("close serial reader for %s: %v", unused.config.DeviceID, err)
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
