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

const (
	defaultSerialParser = "arduino-multisensor-v1"
	mpu6050SerialParser = "mpu6050-imu-v1"
)

var allSupportedResources = []string{
	"temperature_raw",
	"light_raw",
	"magnetic_raw",
	"acceleration_x_raw",
	"acceleration_y_raw",
	"acceleration_z_raw",
}

type serialResourceSpec struct {
	ValueType  string
	SourceName string
}

var serialParserResourceOrder = map[string][]string{
	defaultSerialParser: allSupportedResources,
	mpu6050SerialParser: {
		"acceleration_x",
		"acceleration_y",
		"acceleration_z",
		"gyro_x",
		"gyro_y",
		"gyro_z",
	},
}

var serialParserResources = map[string]map[string]serialResourceSpec{
	defaultSerialParser: {
		"temperature_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "temperature",
		},
		"light_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "light",
		},
		"magnetic_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "magnetic",
		},
		"acceleration_x_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "acceleration_x",
		},
		"acceleration_y_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "acceleration_y",
		},
		"acceleration_z_raw": {
			ValueType: common.ValueTypeInt32, SourceName: "acceleration_z",
		},
	},
	mpu6050SerialParser: {
		"acceleration_x": {
			ValueType: common.ValueTypeFloat64, SourceName: "acceleration_x",
		},
		"acceleration_y": {
			ValueType: common.ValueTypeFloat64, SourceName: "acceleration_y",
		},
		"acceleration_z": {
			ValueType: common.ValueTypeFloat64, SourceName: "acceleration_z",
		},
		"gyro_x": {
			ValueType: common.ValueTypeFloat64, SourceName: "gyro_x",
		},
		"gyro_y": {
			ValueType: common.ValueTypeFloat64, SourceName: "gyro_y",
		},
		"gyro_z": {
			ValueType: common.ValueTypeFloat64, SourceName: "gyro_z",
		},
	},
}

var supportedResources = func() map[string]struct{} {
	resources := make(map[string]struct{})
	for _, parserResources := range serialParserResources {
		for name := range parserResources {
			resources[name] = struct{}{}
		}
	}
	return resources
}()

func normalizedSerialParser(parser string) string {
	if parser == "" {
		return defaultSerialParser
	}
	return parser
}

type managedReader interface {
	Run(ctx context.Context)
	Close() error
}

type readerFactory func(config SerialConfig, options ReaderOptions) managedReader

type managedConnection struct {
	reader managedReader
	cancel context.CancelFunc
	config SerialConfig
	// routes maps one physical resource to consumer Device names. The bool is
	// true for the aggregate "*" Device. During migration, one aggregate
	// physical Device may coexist with one legacy per-resource virtual Device.
	routes   map[string]map[string]bool
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
	cache       *recentCache
	recovery    *serialRecoveryMetrics
	retryDelays []time.Duration
	now         func() int64
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
		cache:       newRecentCache(recentCacheMaxAge, recentCacheMaxSamples),
		recovery:    newSerialRecoveryMetrics(defaultSerialRecoveryTarget),
		retryDelays: append([]time.Duration(nil), defaultSerialReconnectDelays...),
		now:         func() int64 { return time.Now().UnixNano() },
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
	driverConfigs := sdk.DriverConfigs()
	cacheConfig, err := parseRecentCacheConfig(driverConfigs)
	if err != nil {
		return fmt.Errorf("invalid local data cache configuration: %w", err)
	}
	recoveryConfig, err := parseSerialRecoveryConfig(driverConfigs)
	if err != nil {
		return fmt.Errorf("invalid serial recovery configuration: %w", err)
	}
	cacheMetrics := newLocalDataCacheMetrics()
	cache, err := newConfiguredRecentCache(cacheConfig, cacheMetrics.observe)
	if err != nil {
		return err
	}
	recoveryMetrics := newSerialRecoveryMetrics(recoveryConfig.target)
	metricsManager := sdk.MetricsManager()
	if err := cacheMetrics.register(metricsManager); err != nil {
		return err
	}
	if err := recoveryMetrics.register(metricsManager); err != nil {
		return err
	}
	driver.sdk = sdk
	driver.logger = sdk.LoggingClient()
	driver.async = async
	driver.cache = cache
	driver.recovery = recoveryMetrics
	driver.retryDelays = append([]time.Duration(nil), recoveryConfig.reconnectDelays...)
	driver.ctx, driver.cancel = context.WithCancel(context.Background())
	return nil
}

func (driver *Driver) Start() error {
	driver.mu.RLock()
	sdk := driver.sdk
	clock := driver.now
	driver.mu.RUnlock()
	if sdk == nil {
		return errors.New("serial driver is not initialized")
	}
	api := newLocalDataAPI(driver.cache, driver.isKnownLocalSource)
	api.now = clock
	if err := sdk.AddCustomRoute(
		latestRoute,
		interfaces.Unauthenticated,
		api.latest,
		http.MethodGet,
	); err != nil {
		return fmt.Errorf("register local latest route: %w", err)
	}
	if err := sdk.AddCustomRoute(
		recentRoute,
		interfaces.Unauthenticated,
		api.recent,
		http.MethodGet,
	); err != nil {
		return fmt.Errorf("register local recent route: %w", err)
	}
	if err := sdk.AddCustomRoute(
		statsRoute,
		interfaces.Unauthenticated,
		api.stats,
		http.MethodGet,
	); err != nil {
		return fmt.Errorf("register local stats route: %w", err)
	}
	if err := sdk.AddCustomRoute(
		serialRecoveryStatsRoute,
		interfaces.Unauthenticated,
		driver.recovery.stats,
		http.MethodGet,
	); err != nil {
		return fmt.Errorf("register serial recovery stats route: %w", err)
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
		for _, resourceName := range config.resourceNames() {
			for routedDevice, aggregate := range target.routes[resourceName] {
				if routedDevice == deviceName {
					continue
				}
				if (config.ResourceName == "*" && aggregate) ||
					(config.ResourceName != "*" && !aggregate) {
					driver.mu.Unlock()
					return fmt.Errorf(
						"serial resource %q is already routed to %q",
						resourceName,
						routedDevice,
					)
				}
			}
		}
	}

	current := driver.bindings[deviceName]
	if current != nil {
		for _, resourceName := range current.config.resourceNames() {
			removeResourceRoute(
				current.connection,
				resourceName,
				deviceName,
			)
		}
		delete(driver.bindings, deviceName)
		driver.cache.deleteDevice(deviceName)
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
			routes: make(map[string]map[string]bool),
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
			OnRecoveryStarted: func(detectedAt time.Time) {
				driver.handleRecoveryStarted(target, detectedAt)
			},
			OnRecovery: func(observation RecoveryObservation) {
				driver.handleRecovery(target, observation)
			},
			ReconnectDelays: append([]time.Duration(nil), driver.retryDelays...),
		}
		target.reader = driver.newReader(config, options)
		driver.connections[key] = target
		created = target
	}
	for _, resourceName := range config.resourceNames() {
		if target.routes[resourceName] == nil {
			target.routes[resourceName] = make(map[string]bool)
		}
		target.routes[resourceName][deviceName] = config.ResourceName == "*"
	}
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
	config, err := validateDeviceConfig(deviceName, protocols)
	if err != nil {
		return nil, err
	}
	resourceSpecs := serialParserResources[normalizedSerialParser(config.Parser)]

	now := driver.now()
	values := make([]cachedSample, len(requests))
	for index, request := range requests {
		spec, ok := resourceSpecs[request.DeviceResourceName]
		if !ok {
			return nil, fmt.Errorf("unsupported serial resource %q", request.DeviceResourceName)
		}
		if request.Type != spec.ValueType {
			return nil, fmt.Errorf(
				"resource %q must use %s",
				request.DeviceResourceName,
				spec.ValueType,
			)
		}
		latest, ok := driver.cache.latest(deviceName, request.DeviceResourceName, now)
		if !ok {
			return nil, fmt.Errorf("no recent reading for %s/%s", deviceName, request.DeviceResourceName)
		}
		if latest.ValueType != spec.ValueType {
			return nil, fmt.Errorf(
				"cached resource %q has unexpected type %s",
				request.DeviceResourceName,
				latest.ValueType,
			)
		}
		values[index] = latest
	}

	result := make([]*sdkModels.CommandValue, len(requests))
	for index, request := range requests {
		commandValue, err := sdkModels.NewCommandValueWithOrigin(
			request.DeviceResourceName,
			values[index].ValueType,
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
	cacheErrors := make([]error, 0)

	driver.mu.Lock()
	if driver.connections[managed.config.key()] != managed || driver.stopped {
		driver.mu.Unlock()
		return
	}
	resourceSpecs := serialParserResources[normalizedSerialParser(managed.config.Parser)]
	for _, reading := range sample.Readings {
		spec, ok := resourceSpecs[reading.ResourceName]
		if !ok {
			continue
		}
		routedDevices := managed.routes[reading.ResourceName]
		if len(routedDevices) == 0 {
			continue
		}
		value, err := reading.typedValue(spec.ValueType)
		if err != nil {
			cacheErrors = append(cacheErrors, err)
			continue
		}
		for deviceName, aggregate := range routedDevices {
			eventSourceName := spec.SourceName
			if aggregate {
				eventSourceName = reading.ResourceName
			}
			commandValue, err := sdkModels.NewCommandValueWithOrigin(
				reading.ResourceName,
				spec.ValueType,
				value,
				origin,
			)
			if err != nil {
				driver.mu.Unlock()
				driver.warn("create async serial reading for %s/%s: %v", deviceName, reading.ResourceName, err)
				return
			}
			if err := driver.cache.appendChecked(deviceName, reading.ResourceName, cachedSample{
				Origin:    origin,
				ValueType: spec.ValueType,
				Value:     value,
			}); err != nil {
				cacheErrors = append(cacheErrors, fmt.Errorf(
					"cache %s/%s: %w",
					deviceName,
					reading.ResourceName,
					err,
				))
				continue
			}
			events = append(events, routedEvent{
				deviceName: deviceName,
				sourceName: eventSourceName,
				value:      commandValue,
			})
		}
	}
	async := driver.async
	ctx := driver.ctx
	driver.mu.Unlock()

	for _, err := range cacheErrors {
		driver.warn("discarding serial telemetry: %v", err)
	}
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
		for _, routedDevices := range managed.routes {
			for deviceName := range routedDevices {
				deviceSet[deviceName] = struct{}{}
			}
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

func (driver *Driver) handleRecoveryStarted(
	managed *managedConnection,
	detectedAt time.Time,
) {
	driver.mu.RLock()
	active := driver.connections[managed.config.key()] == managed && !driver.stopped
	metrics := driver.recovery
	driver.mu.RUnlock()
	if !active || metrics == nil {
		return
	}
	metrics.observeStarted()
	driver.info(
		"serial recovery started for %s at %d",
		managed.config.DeviceID,
		detectedAt.UnixNano(),
	)
}

func (driver *Driver) handleRecovery(
	managed *managedConnection,
	observation RecoveryObservation,
) {
	driver.mu.RLock()
	active := driver.connections[managed.config.key()] == managed && !driver.stopped
	metrics := driver.recovery
	driver.mu.RUnlock()
	if !active || metrics == nil {
		return
	}
	metrics.observeCompleted(observation)
	message := "serial recovery completed for %s in %.3fms after %d open attempts " +
		"(detect-to-port-ready %.3fms, port-ready-to-first-byte %.3fms, " +
		"first-byte-to-valid-frame %.3fms, target %.3fms)"
	arguments := []any{
		managed.config.DeviceID,
		float64(observation.Duration) / float64(time.Millisecond),
		observation.Attempts,
		elapsedMilliseconds(observation.DetectedAt, observation.PortReadyAt),
		elapsedMilliseconds(observation.PortReadyAt, observation.FirstByteAt),
		elapsedMilliseconds(observation.FirstByteAt, observation.ResumedAt),
		float64(metrics.target) / float64(time.Millisecond),
	}
	if observation.Duration > metrics.target {
		driver.warn(message, arguments...)
		return
	}
	driver.info(message, arguments...)
}

func (driver *Driver) stopDevice(deviceName string, clearLatest bool) {
	driver.mu.Lock()
	binding := driver.bindings[deviceName]
	var unused *managedConnection
	if binding != nil {
		for _, resourceName := range binding.config.resourceNames() {
			removeResourceRoute(
				binding.connection,
				resourceName,
				deviceName,
			)
		}
		delete(driver.bindings, deviceName)
		if len(binding.connection.routes) == 0 {
			delete(driver.connections, binding.config.key())
			unused = binding.connection
		}
	}
	if clearLatest {
		driver.cache.deleteDevice(deviceName)
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

func removeResourceRoute(
	connection *managedConnection,
	resourceName string,
	deviceName string,
) {
	routedDevices := connection.routes[resourceName]
	delete(routedDevices, deviceName)
	if len(routedDevices) == 0 {
		delete(connection.routes, resourceName)
	}
}

func (driver *Driver) isKnownLocalSource(deviceName string, resourceName string) bool {
	driver.mu.RLock()
	defer driver.mu.RUnlock()
	binding := driver.bindings[deviceName]
	if binding == nil || driver.stopped {
		return false
	}
	for _, known := range binding.config.resourceNames() {
		if known == resourceName {
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

func (driver *Driver) info(message string, args ...any) {
	driver.mu.RLock()
	loggingClient := driver.logger
	driver.mu.RUnlock()
	if loggingClient != nil {
		loggingClient.Infof(message, args...)
	}
}
