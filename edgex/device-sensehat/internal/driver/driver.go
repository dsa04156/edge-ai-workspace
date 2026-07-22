package driver

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/edgexfoundry/device-sdk-go/v4/pkg/interfaces"
	sdkModels "github.com/edgexfoundry/device-sdk-go/v4/pkg/models"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/clients/logger"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
)

var _ interfaces.ProtocolDriver = (*Driver)(nil)

type managedSource interface {
	Run(ctx context.Context)
	Close() error
}

type sourceFactory func(config I2CConfig, options SourceOptions) managedSource

type managedConnection struct {
	source   managedSource
	cancel   context.CancelFunc
	config   I2CConfig
	routes   map[string]string
	state    models.OperatingState
	hasState bool
}

type deviceBinding struct {
	config     I2CConfig
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
	cache       *recentCache
	now         func() int64
	newSource   sourceFactory
	stopped     bool
}

func NewDriver() *Driver {
	return newDriver(func(config I2CConfig, options SourceOptions) managedSource {
		return NewSource(config, options)
	})
}

func newDriver(factory sourceFactory) *Driver {
	return &Driver{
		connections: make(map[connectionKey]*managedConnection),
		bindings:    make(map[string]*deviceBinding),
		cache:       newRecentCache(recentCacheMaxAge, recentCacheMaxSamples),
		now:         func() int64 { return time.Now().UnixNano() },
		newSource:   factory,
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
		return errors.New("Sense HAT driver is already initialized")
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
	clock := driver.now
	driver.mu.RUnlock()
	if sdk == nil {
		return errors.New("Sense HAT driver is not initialized")
	}
	api := newLocalDataAPI(driver.cache, driver.isKnownLocalSource)
	api.now = clock
	if err := sdk.AddCustomRoute(latestRoute, interfaces.Unauthenticated, api.latest, http.MethodGet); err != nil {
		return fmt.Errorf("register local latest route: %w", err)
	}
	if err := sdk.AddCustomRoute(recentRoute, interfaces.Unauthenticated, api.recent, http.MethodGet); err != nil {
		return fmt.Errorf("register local recent route: %w", err)
	}
	for _, device := range sdk.Devices() {
		if err := driver.UpdateDevice(device.Name, device.Protocols, device.AdminState); err != nil {
			return fmt.Errorf("start Sense HAT device %q: %w", device.Name, err)
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
		if err := current.source.Close(); err != nil {
			closeErrors = append(closeErrors, err)
		}
	}
	return errors.Join(closeErrors...)
}

func (driver *Driver) AddDevice(deviceName string, protocols map[string]models.ProtocolProperties, adminState models.AdminState) error {
	return driver.UpdateDevice(deviceName, protocols, adminState)
}

func (driver *Driver) UpdateDevice(deviceName string, protocols map[string]models.ProtocolProperties, adminState models.AdminState) error {
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
	var sourceContext context.Context
	var sourceCancel context.CancelFunc
	var knownState *models.OperatingState
	var sdk interfaces.DeviceServiceSDK

	driver.mu.Lock()
	if driver.sdk == nil || driver.ctx == nil {
		driver.mu.Unlock()
		return errors.New("Sense HAT driver is not initialized")
	}
	if driver.stopped {
		driver.mu.Unlock()
		return errors.New("Sense HAT driver is stopped")
	}
	if current := driver.bindings[deviceName]; current != nil && current.config == config {
		driver.mu.Unlock()
		return nil
	}

	key := config.key()
	target := driver.connections[key]
	if target != nil {
		if routedDevice, ok := target.routes[config.ResourceGroup]; ok && routedDevice != deviceName {
			driver.mu.Unlock()
			return fmt.Errorf("i2c resource group %q is already routed to %q", config.ResourceGroup, routedDevice)
		}
	}
	current := driver.bindings[deviceName]
	if current != nil {
		delete(current.connection.routes, current.config.ResourceGroup)
		delete(driver.bindings, deviceName)
		driver.cache.deleteDevice(deviceName)
		if len(current.connection.routes) == 0 && current.connection != target {
			delete(driver.connections, current.config.key())
			obsolete = current.connection
		}
	}
	if target == nil {
		sourceContext, sourceCancel = context.WithCancel(driver.ctx)
		target = &managedConnection{
			cancel: sourceCancel,
			config: config,
			routes: make(map[string]string),
		}
		options := SourceOptions{
			OnSample: func(sample Sample) { driver.handleSample(target, sample) },
			OnState:  func(state models.OperatingState) { driver.handleState(target, state) },
			OnInvalidLine: func(err error) {
				driver.warn("discarding malformed Sense HAT telemetry for %s: %v", config.DeviceID, err)
			},
			OnDiagnostic: func(line string) {
				driver.warn("Sense HAT reader diagnostic for %s: %s", config.DeviceID, line)
			},
		}
		target.source = driver.newSource(config, options)
		driver.connections[key] = target
		created = target
	}
	target.routes[config.ResourceGroup] = deviceName
	driver.bindings[deviceName] = &deviceBinding{config: config, connection: target}
	driver.cache.deleteDevice(deviceName)
	if target.hasState {
		state := target.state
		knownState = &state
	}
	sdk = driver.sdk
	driver.mu.Unlock()

	if obsolete != nil {
		obsolete.cancel()
		if err := obsolete.source.Close(); err != nil {
			driver.warn("close unused Sense HAT source for %s: %v", obsolete.config.DeviceID, err)
		}
	}
	if created != nil {
		go created.source.Run(sourceContext)
	}
	if knownState != nil {
		if err := sdk.UpdateDeviceOperatingState(deviceName, *knownState); err != nil {
			driver.warn("update operating state for %s to %s: %v", deviceName, *knownState, err)
		}
	}
	return nil
}

func (driver *Driver) RemoveDevice(deviceName string, protocols map[string]models.ProtocolProperties) error {
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
	config, err := ParseI2CConfig(protocols)
	if err != nil {
		return nil, err
	}
	allowed := resourceGroups[config.ResourceGroup]
	now := driver.now()
	values := make([]cachedSample, len(requests))
	for index, request := range requests {
		if request.Type != common.ValueTypeFloat64 {
			return nil, fmt.Errorf("resource %q must use %s", request.DeviceResourceName, common.ValueTypeFloat64)
		}
		if !containsResource(allowed, request.DeviceResourceName) {
			return nil, fmt.Errorf("resource %q is not part of i2c group %q", request.DeviceResourceName, config.ResourceGroup)
		}
		latest, ok := driver.cache.latest(deviceName, request.DeviceResourceName, now)
		if !ok {
			return nil, fmt.Errorf("no recent reading for %s/%s", deviceName, request.DeviceResourceName)
		}
		values[index] = latest
	}
	result := make([]*sdkModels.CommandValue, len(requests))
	for index, request := range requests {
		commandValue, err := sdkModels.NewCommandValueWithOrigin(
			request.DeviceResourceName,
			common.ValueTypeFloat64,
			values[index].Value,
			values[index].Origin,
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
	return errors.New("Sense HAT I2C device is read-only")
}

func (driver *Driver) Discover() error {
	return errors.New("Sense HAT I2C device discovery is not supported")
}

func (driver *Driver) ValidateDevice(device models.Device) error {
	_, err := validateDeviceConfig(device.Name, device.Protocols)
	return err
}

func validateDeviceConfig(deviceName string, protocols map[string]models.ProtocolProperties) (I2CConfig, error) {
	config, err := ParseI2CConfig(protocols)
	if err != nil {
		return I2CConfig{}, err
	}
	if deviceName == "" {
		return I2CConfig{}, errors.New("EdgeX device name is required")
	}
	return config, nil
}

func (driver *Driver) handleSample(managed *managedConnection, sample Sample) {
	if sample.DeviceID != managed.config.DeviceID {
		driver.warn("discarding Sense HAT telemetry with unexpected physical device %q", sample.DeviceID)
		return
	}
	type routedEvent struct {
		deviceName string
		sourceName string
		values     []*sdkModels.CommandValue
	}
	resourceValues := sample.ResourceValues()
	events := make([]routedEvent, 0, len(managed.routes))

	driver.mu.Lock()
	if driver.connections[managed.config.key()] != managed || driver.stopped {
		driver.mu.Unlock()
		return
	}
	for group, deviceName := range managed.routes {
		resources := resourceGroups[group]
		commandValues := make([]*sdkModels.CommandValue, 0, len(resources))
		valid := true
		for _, resourceName := range resources {
			value, ok := resourceValues[resourceName]
			if !ok {
				valid = false
				break
			}
			commandValue, err := sdkModels.NewCommandValueWithOrigin(
				resourceName,
				common.ValueTypeFloat64,
				value,
				sample.Origin,
			)
			if err != nil {
				valid = false
				break
			}
			driver.cache.append(deviceName, resourceName, cachedSample{
				Origin: sample.Origin, ValueType: common.ValueTypeFloat64, Value: value,
			})
			commandValues = append(commandValues, commandValue)
		}
		if valid {
			events = append(events, routedEvent{deviceName: deviceName, sourceName: group, values: commandValues})
		}
	}
	async := driver.async
	ctx := driver.ctx
	driver.mu.Unlock()

	for _, routed := range events {
		event := &sdkModels.AsyncValues{
			DeviceName: routed.deviceName, SourceName: routed.sourceName, CommandValues: routed.values,
		}
		select {
		case async <- event:
		case <-ctx.Done():
			return
		}
	}
}

func (driver *Driver) handleState(managed *managedConnection, state models.OperatingState) {
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

func (driver *Driver) stopDevice(deviceName string, clearCache bool) {
	driver.mu.Lock()
	binding := driver.bindings[deviceName]
	var unused *managedConnection
	if binding != nil {
		delete(binding.connection.routes, binding.config.ResourceGroup)
		delete(driver.bindings, deviceName)
		if len(binding.connection.routes) == 0 {
			delete(driver.connections, binding.config.key())
			unused = binding.connection
		}
	}
	if clearCache {
		driver.cache.deleteDevice(deviceName)
	}
	driver.mu.Unlock()
	if unused == nil {
		return
	}
	unused.cancel()
	if err := unused.source.Close(); err != nil {
		driver.warn("close Sense HAT source for %s: %v", unused.config.DeviceID, err)
	}
}

func (driver *Driver) isKnownLocalSource(deviceName string, resourceName string) bool {
	driver.mu.RLock()
	defer driver.mu.RUnlock()
	binding := driver.bindings[deviceName]
	return binding != nil && containsResource(resourceGroups[binding.config.ResourceGroup], resourceName) && !driver.stopped
}

func containsResource(resources []string, resourceName string) bool {
	for _, candidate := range resources {
		if candidate == resourceName {
			return true
		}
	}
	return false
}

func (driver *Driver) warn(message string, args ...any) {
	driver.mu.RLock()
	loggingClient := driver.logger
	driver.mu.RUnlock()
	if loggingClient != nil {
		loggingClient.Warnf(message, args...)
	}
}
