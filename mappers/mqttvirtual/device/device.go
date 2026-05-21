package device

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"sync"
	"time"

	"k8s.io/klog/v2"

	dmiapi "github.com/kubeedge/api/apis/dmi/v1beta1"
	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mapper-framework/pkg/global"
	"github.com/kubeedge/mapper-framework/pkg/util/parse"
	dbInflux "github.com/kubeedge/mqttvirtual/data/dbmethod/influxdb2"
	dbMysql "github.com/kubeedge/mqttvirtual/data/dbmethod/mysql"
	dbRedis "github.com/kubeedge/mqttvirtual/data/dbmethod/redis"
	dbTdengine "github.com/kubeedge/mqttvirtual/data/dbmethod/tdengine"
	httpMethod "github.com/kubeedge/mqttvirtual/data/publish/http"
	mqttMethod "github.com/kubeedge/mqttvirtual/data/publish/mqtt"
	otelMethod "github.com/kubeedge/mqttvirtual/data/publish/otel"
	"github.com/kubeedge/mqttvirtual/data/stream"
	"github.com/kubeedge/mqttvirtual/driver"
	"github.com/kubeedge/mqttvirtual/status"
)

const (
	defaultDeviceStatusFlushInterval = 30 * time.Second
	defaultDeviceStatusJitter        = 10 * time.Second
	defaultDeviceStatusHeartbeat     = 120 * time.Second
)

type DevPanel struct {
	deviceMuxs   map[string]context.CancelFunc
	devices      map[string]*driver.CustomizedDev
	models       map[string]common.DeviceModel
	wg           sync.WaitGroup
	serviceMutex sync.RWMutex
	quitChan     chan os.Signal
}

func syncDesiredToCommand(visitorConfig *driver.VisitorConfig, twin *common.Twin, dev *driver.CustomizedDev) error {
	if visitorConfig == nil || twin == nil || twin.Property == nil || dev == nil || dev.CustomizedClient == nil {
		return nil
	}
	if twin.Property.PProperty.AccessMode == "ReadOnly" {
		return nil
	}
	if twin.ObservedDesired.Value == "" {
		return nil
	}

	klog.V(2).Infof("Apply desired command device=%s property=%s value=%s", dev.Instance.Name, twin.PropertyName, twin.ObservedDesired.Value)
	convertedValue, err := common.Convert(twin.Property.PProperty.DataType, twin.ObservedDesired.Value)
	if err != nil {
		klog.Errorf("Failed to convert desired value as %s : %v", twin.Property.PProperty.DataType, err)
		return err
	}
	if err := dev.CustomizedClient.PublishCommand(visitorConfig, twin.PropertyName, convertedValue); err != nil {
		return fmt.Errorf("%s publish desired command error: %v", twin.PropertyName, err)
	}
	return nil
}

var (
	devPanel *DevPanel
	once     sync.Once
)

var ErrEmptyData = errors.New("device or device model list is empty")

// NewDevPanel init and return devPanel
func NewDevPanel() *DevPanel {
	once.Do(func() {
		devPanel = &DevPanel{
			deviceMuxs:   make(map[string]context.CancelFunc),
			devices:      make(map[string]*driver.CustomizedDev),
			models:       make(map[string]common.DeviceModel),
			wg:           sync.WaitGroup{},
			serviceMutex: sync.RWMutex{},
			quitChan:     make(chan os.Signal),
		}
	})
	return devPanel
}

// DevStart start all devices.
func (d *DevPanel) DevStart() {
	devices := d.snapshotDevices()
	for id, dev := range devices {
		klog.V(4).Info("Dev: ", id, dev)
		ctx, cancel := context.WithCancel(context.Background())
		d.serviceMutex.Lock()
		d.deviceMuxs[id] = cancel
		d.wg.Add(1)
		d.serviceMutex.Unlock()
		go d.start(ctx, dev)
	}
	signal.Notify(d.quitChan, os.Interrupt)
	go func() {
		<-d.quitChan
		for id, device := range d.snapshotDevices() {
			if err := stopCustomizedDevice(device, id); err != nil {
				klog.Errorf("Service has stopped but failed to stop %s:%v", id, err)
			}
		}
		klog.V(1).Info("Exit mapper")
		os.Exit(1)
	}()
	d.wg.Wait()
}

func (d *DevPanel) snapshotDevices() map[string]*driver.CustomizedDev {
	d.serviceMutex.RLock()
	defer d.serviceMutex.RUnlock()
	devices := make(map[string]*driver.CustomizedDev, len(d.devices))
	for id, dev := range d.devices {
		devices[id] = dev
	}
	return devices
}

// start the device
func (d *DevPanel) start(ctx context.Context, dev *driver.CustomizedDev) {
	defer d.wg.Done()
	if dev == nil {
		klog.Error("start called with nil device")
		return
	}

	var protocolConfig driver.ProtocolConfig
	if err := json.Unmarshal(dev.Instance.PProtocol.ConfigData, &protocolConfig); err != nil {
		klog.Errorf("Unmarshal ProtocolConfigs error: %v", err)
		return
	}
	client, err := driver.NewClient(protocolConfig)
	if err != nil {
		klog.Errorf("Init dev %s error: %v", dev.Instance.Name, err)
		return
	}
	dev.CustomizedClient = client
	err = dev.CustomizedClient.InitDevice()
	if err != nil {
		klog.Errorf("Init device %s error: %v", dev.Instance.ID, err)
		return
	}
	go dataHandler(ctx, dev)
	<-ctx.Done()
}

// dataHandler initialize the timer to handle data plane and devicetwin.
func dataHandler(ctx context.Context, dev *driver.CustomizedDev) {
	if dev == nil || dev.CustomizedClient == nil {
		klog.Error("dataHandler skipped because device or customized client is nil")
		return
	}
	// handle device status report
	getStates := &DeviceStates{
		Client:          dev.CustomizedClient,
		DeviceName:      dev.Instance.Name,
		DeviceNamespace: dev.Instance.Namespace,
		ReportToCloud:   dev.Instance.Status.ReportToCloud,
		ReportCycle:     time.Millisecond * time.Duration(dev.Instance.Status.ReportCycle),
	}
	go getStates.Run(ctx)
	// handle device twin report
	eventTwinData := make(map[string]*TwinData)
	for _, twin := range dev.Instance.Twins {
		if twin.Property == nil {
			klog.Warningf("skip unresolved twin %q for device %s", twin.PropertyName, dev.Instance.Name)
			continue
		}
		twin.Property.PProperty.DataType = strings.ToLower(twin.Property.PProperty.DataType)
		var visitorConfig driver.VisitorConfig

		err := json.Unmarshal(twin.Property.Visitors, &visitorConfig)
		if err != nil {
			klog.Errorf("Unmarshal VisitorConfig device=%s property=%s error: %v", dev.Instance.Name, twin.PropertyName, err)
			continue
		}
		visitorConfig.VisitorConfigData.DataType = strings.ToLower(visitorConfig.VisitorConfigData.DataType)
		err = syncDesiredToCommand(&visitorConfig, &twin, dev)
		if err != nil {
			klog.Error(err)
		}

		// If the device property type is streaming, it will directly enter the streaming data processing function,
		// such as saving frames or saving videos, and will no longer push it to the user database and application.
		// If there are other needs for stream data processing, users can add functions in the mapper/data/stream directory.
		if twin.Property.PProperty.DataType == "stream" {
			err = stream.StreamHandler(&twin, dev.CustomizedClient, &visitorConfig)
			if err != nil {
				klog.Errorf("processed streaming data by %s Error: %v", twin.PropertyName, err)
			}
			continue
		}

		// handle twin
		twinData := &TwinData{
			DeviceName:      dev.Instance.Name,
			DeviceNamespace: dev.Instance.Namespace,
			Client:          dev.CustomizedClient,
			Name:            twin.PropertyName,
			Type:            twin.ObservedDesired.Metadata.Type,
			ObservedDesired: twin.ObservedDesired,
			VisitorConfig:   &visitorConfig,
			Topic:           fmt.Sprintf(common.TopicTwinUpdate, dev.Instance.ID),
			CollectCycle:    time.Millisecond * time.Duration(twin.Property.CollectCycle),
			ReportToCloud:   twin.Property.ReportToCloud,
		}
		if twinData.ReportToCloud && shouldReportAsTwinProperty(&twin) {
			eventTwinData[visitorConfig.JsonKey] = twinData
		}

		if !shouldProcessMapperControlStatusProperty(&twin) {
			klog.V(4).Infof("skip mapper-framework data export for raw telemetry property device=%s property=%s", dev.Instance.Name, twin.PropertyName)
			continue
		}

		dataModel := common.NewDataModel(dev.Instance.Name, twin.Property.PropertyName, dev.Instance.Namespace, common.WithType(twin.ObservedDesired.Metadata.Type))
		// handle push method
		if twin.Property.PushMethod.MethodConfig != nil && twin.Property.PushMethod.MethodName != "" {
			pushHandler(ctx, &twin, dev.CustomizedClient, &visitorConfig, dataModel)
		}
		// handle database
		if twin.Property.PushMethod.DBMethod.DBMethodName != "" {
			dbHandler(ctx, &twin, dev.CustomizedClient, &visitorConfig, dataModel)
		}
	}
	if len(eventTwinData) > 0 {
		go runEventTwinReporter(ctx, dev, eventTwinData)
	}
}

func shouldReportAsTwinProperty(twin *common.Twin) bool {
	if twin == nil || twin.Property == nil {
		return false
	}
	return status.IsSummaryField(twin.PropertyName)
}

func shouldProcessMapperControlStatusProperty(twin *common.Twin) bool {
	if twin == nil || twin.Property == nil {
		return false
	}
	return status.IsSummaryField(twin.PropertyName)
}

func runEventTwinReporter(ctx context.Context, dev *driver.CustomizedDev, eventTwinData map[string]*TwinData) {
	if dev == nil || dev.CustomizedClient == nil || dev.CustomizedClient.Events == nil {
		return
	}

	flushInterval := durationFromEnv("DEVICE_STATUS_FLUSH_SECONDS", defaultDeviceStatusFlushInterval)
	jitter := durationFromEnv("DEVICE_STATUS_JITTER_SECONDS", defaultDeviceStatusJitter)
	heartbeatInterval := durationFromEnv("DEVICE_STATUS_HEARTBEAT_SECONDS", defaultDeviceStatusHeartbeat)
	pending := make(map[string]*TwinData)
	lastReported := make(map[string]string)
	lastReportTime := make(map[string]time.Time)
	timer := time.NewTimer(nextFlushDelay(flushInterval, jitter))
	defer func() {
		if !timer.Stop() {
			select {
			case <-timer.C:
			default:
			}
		}
	}()

	flush := func() {
		if len(pending) == 0 {
			return
		}

		summary := status.Summary{
			DeviceName:      dev.Instance.Name,
			DeviceNamespace: dev.Instance.Namespace,
			Source:          "mapper-framework",
			Values:          make(map[string]string, len(pending)),
		}
		nextPending := make(map[string]*TwinData)
		for key, twinData := range pending {
			statusSummary, err := twinData.BuildStatusSummary()
			if err != nil {
				klog.Errorf("event-driven status summary build failed for %s/%s: %v", dev.Instance.Name, key, err)
				continue
			}
			for statusKey, currentValue := range statusSummary.Values {
				lastValue, reportedBefore := lastReported[statusKey]
				lastSentAt, sentBefore := lastReportTime[statusKey]
				changed := !reportedBefore || lastValue != currentValue
				heartbeatDue := !sentBefore || time.Since(lastSentAt) >= heartbeatInterval
				if !changed && !heartbeatDue {
					continue
				}
				if sentBefore && time.Since(lastSentAt) < flushInterval {
					nextPending[key] = twinData
					continue
				}
				lastReported[statusKey] = currentValue
				lastReportTime[statusKey] = time.Now()
				summary.Values[statusKey] = currentValue
			}
		}
		pending = nextPending

		if len(summary.Values) == 0 {
			return
		}

		if err := (status.DMIReporter{}).Report(ctx, summary); err != nil {
			klog.Errorf("fail to report device status summary of %s with err: %+v", summary.DeviceName, err)
		}
	}

	for {
		select {
		case payload := <-dev.CustomizedClient.Events:
			for key := range payload {
				twinData, ok := eventTwinData[key]
				if !ok {
					continue
				}
				pending[key] = twinData
			}
		case <-timer.C:
			flush()
			timer.Reset(nextFlushDelay(flushInterval, jitter))
		case <-ctx.Done():
			for len(dev.CustomizedClient.Events) > 0 {
				payload := <-dev.CustomizedClient.Events
				for key := range payload {
					if twinData, ok := eventTwinData[key]; ok {
						pending[key] = twinData
					}
				}
			}
			flush()
			return
		}
	}
}

var deviceStatusPropertyAllowlist = status.AllowedSummaryFields()

func durationFromEnv(name string, fallback time.Duration) time.Duration {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback
	}
	seconds, err := strconv.Atoi(raw)
	if err != nil || seconds <= 0 {
		klog.Warningf("invalid %s=%q, using %s", name, raw, fallback)
		return fallback
	}
	return time.Duration(seconds) * time.Second
}

func nextFlushDelay(interval, jitter time.Duration) time.Duration {
	if jitter <= 0 {
		return interval
	}
	return interval + time.Duration(rand.Int63n(int64(jitter)))
}

// pushHandler start data panel work
func pushHandler(ctx context.Context, twin *common.Twin, client *driver.CustomizedClient, visitorConfig *driver.VisitorConfig, dataModel *common.DataModel) {
	if twin == nil || twin.Property == nil || client == nil || visitorConfig == nil || dataModel == nil {
		klog.Warning("skip push handler because twin/client/visitor/dataModel is nil")
		return
	}
	if twin.Property.PushMethod.MethodName == common.PushMethodOTEL {
		otelMethod.DataHandler(ctx, twin, client, visitorConfig, dataModel)
		return
	}

	var dataPanel global.DataPanel
	var err error
	// initialization dataPanel
	switch twin.Property.PushMethod.MethodName {
	case common.PushMethodHTTP:
		dataPanel, err = httpMethod.NewDataPanel(twin.Property.PushMethod.MethodConfig)
	case common.PushMethodMQTT:
		dataPanel, err = mqttMethod.NewDataPanel(twin.Property.PushMethod.MethodConfig)
	default:
		err = errors.New("custom protocols are not currently supported when push data")
	}
	if err != nil {
		klog.Errorf("new data panel error: %v", err)
		return
	}
	// initialization PushMethod
	err = dataPanel.InitPushMethod()
	if err != nil {
		klog.Errorf("init publish method err: %v", err)
		return
	}
	reportCycle := time.Millisecond * time.Duration(twin.Property.ReportCycle)
	if reportCycle == 0 {
		reportCycle = common.DefaultReportCycle
	}
	ticker := time.NewTicker(reportCycle)
	go func() {
		for {
			select {
			case <-ticker.C:
				deviceData, err := client.GetDeviceData(visitorConfig)
				if err != nil {
					klog.Errorf("publish error: %v", err)
					continue
				}
				sData, err := common.ConvertToString(deviceData)
				if err != nil {
					klog.Errorf("Failed to convert publish method data : %v", err)
					continue
				}
				dataModel.SetValue(sData)
				dataModel.SetTimeStamp()
				dataPanel.Push(dataModel)
			case <-ctx.Done():
				return
			}
		}
	}()
}

// dbHandler start db client to save data
func isInfluxDBMethod(name string) bool {
	return name == "influx" || name == "influxdb2"
}

func dbHandler(ctx context.Context, twin *common.Twin, client *driver.CustomizedClient, visitorConfig *driver.VisitorConfig, dataModel *common.DataModel) {
	if twin == nil || twin.Property == nil || client == nil || visitorConfig == nil || dataModel == nil {
		klog.Warning("skip db handler because twin/client/visitor/dataModel is nil")
		return
	}
	methodName := twin.Property.PushMethod.DBMethod.DBMethodName
	if isInfluxDBMethod(methodName) {
		klog.Infof("start influxdb handler device=%s property=%s dbMethod=%s", dataModel.DeviceName, dataModel.PropertyName, methodName)
		dbInflux.DataHandler(ctx, twin, client, visitorConfig, dataModel)
		return
	}

	switch methodName {
	// TODO add more database
	case "redis":
		dbRedis.DataHandler(ctx, twin, client, visitorConfig, dataModel)

	case "tdengine":
		dbTdengine.DataHandler(ctx, twin, client, visitorConfig, dataModel)

	case "mysql":
		dbMysql.DataHandler(ctx, twin, client, visitorConfig, dataModel)
	}
}

// DevInit initialize the device
func (d *DevPanel) DevInit(deviceList []*dmiapi.Device, deviceModelList []*dmiapi.DeviceModel) error {
	if len(deviceList) == 0 || len(deviceModelList) == 0 {
		return ErrEmptyData
	}
	d.serviceMutex.Lock()
	defer d.serviceMutex.Unlock()

	for i := range deviceModelList {
		model := deviceModelList[i]
		cur := parse.GetDeviceModelFromGrpc(model)
		modelID := parse.GetResourceID(model.Namespace, model.Name)
		d.models[modelID] = cur
	}

	for i := range deviceList {
		device := deviceList[i]
		modelID := parse.GetResourceID(device.Namespace, device.Spec.DeviceModelReference)
		commonModel := d.models[modelID]
		protocol, err := parse.BuildProtocolFromGrpc(device)
		if err != nil {
			return err
		}
		instance, err := parse.GetDeviceFromGrpc(device, &commonModel)
		if err != nil {
			return err
		}
		instance.PProtocol = protocol

		cur := new(driver.CustomizedDev)
		cur.Instance = *instance
		d.devices[instance.ID] = cur
	}

	return nil
}

// UpdateDev stop old device, then update and start new device
func (d *DevPanel) UpdateDev(model *common.DeviceModel, device *common.DeviceInstance) {
	if model == nil || device == nil {
		klog.Errorf("UpdateDev skipped because model or device is nil")
		return
	}

	newDev := &driver.CustomizedDev{Instance: *device}
	ctx, cancelFunc := context.WithCancel(context.Background())

	var oldDevice *driver.CustomizedDev
	var oldCancel context.CancelFunc
	d.serviceMutex.Lock()
	oldDevice = d.devices[device.ID]
	oldCancel = d.deviceMuxs[device.ID]
	d.devices[device.ID] = newDev
	d.models[model.ID] = *model
	d.deviceMuxs[device.ID] = cancelFunc
	d.wg.Add(1)
	d.serviceMutex.Unlock()

	if oldCancel != nil {
		oldCancel()
	}
	if err := stopCustomizedDevice(oldDevice, device.ID); err != nil {
		klog.Error(err)
	}
	go d.start(ctx, newDev)
}

// UpdateDevTwins update device's twins
func (d *DevPanel) UpdateDevTwins(deviceID string, twins []common.Twin) error {
	var model common.DeviceModel
	var instance common.DeviceInstance
	d.serviceMutex.Lock()
	dev, ok := d.devices[deviceID]
	if !ok || dev == nil {
		d.serviceMutex.Unlock()
		return fmt.Errorf("device %s not found", deviceID)
	}
	dev.Instance.Twins = twins
	instance = dev.Instance
	model = d.models[dev.Instance.Model]
	d.serviceMutex.Unlock()

	d.UpdateDev(&model, &instance)
	return nil
}

// DealDeviceTwinGet get device's twin data
func (d *DevPanel) DealDeviceTwinGet(deviceID string, twinName string) (interface{}, error) {
	d.serviceMutex.RLock()
	dev, ok := d.devices[deviceID]
	if !ok || dev == nil {
		d.serviceMutex.RUnlock()
		return nil, fmt.Errorf("not found device %s", deviceID)
	}
	twins := append([]common.Twin(nil), dev.Instance.Twins...)
	d.serviceMutex.RUnlock()

	var res []parse.TwinResultResponse
	for _, twin := range twins {
		if twinName != "" && twin.PropertyName != twinName {
			continue
		}
		payload, err := getTwinData(deviceID, twin, dev)
		if err != nil {
			return nil, err
		}
		item := parse.TwinResultResponse{
			PropertyName: twin.PropertyName,
			Payload:      payload,
		}
		res = append(res, item)
	}
	return json.Marshal(res)
}

// getTwinData get twin
func getTwinData(deviceID string, twin common.Twin, dev *driver.CustomizedDev) ([]byte, error) {
	if dev == nil || dev.CustomizedClient == nil {
		return nil, fmt.Errorf("device=%s property=%s customized client is nil", deviceID, twin.PropertyName)
	}
	if twin.Property == nil {
		return nil, fmt.Errorf("device=%s property=%s twin property is nil", deviceID, twin.PropertyName)
	}
	var visitorConfig driver.VisitorConfig
	err := json.Unmarshal(twin.Property.Visitors, &visitorConfig)
	if err != nil {
		return nil, fmt.Errorf("device=%s property=%s unmarshal visitor config failed: %w", deviceID, twin.PropertyName, err)
	}
	twinData := &TwinData{
		DeviceName:    deviceID,
		Client:        dev.CustomizedClient,
		Name:          twin.PropertyName,
		Type:          twin.ObservedDesired.Metadata.Type,
		VisitorConfig: &visitorConfig,
		Topic:         fmt.Sprintf(common.TopicTwinUpdate, deviceID),
	}
	payload, err := twinData.GetPayLoad()
	if err != nil {
		return nil, fmt.Errorf("device=%s property=%s get twin payload failed: %w", deviceID, twin.PropertyName, err)
	}
	return payload, nil
}

// GetDevice get device instance
func (d *DevPanel) GetDevice(deviceID string) (interface{}, error) {
	d.serviceMutex.RLock()
	found, ok := d.devices[deviceID]
	if !ok || found == nil {
		d.serviceMutex.RUnlock()
		return nil, fmt.Errorf("device %s not found", deviceID)
	}
	instance := found.Instance
	d.serviceMutex.RUnlock()

	// get the latest reported twin value
	for i, twin := range instance.Twins {
		payload, err := getTwinData(deviceID, twin, found)
		if err != nil {
			return nil, err
		}
		instance.Twins[i].Reported.Value = string(payload)
	}
	return &driver.CustomizedDev{Instance: instance, CustomizedClient: found.CustomizedClient}, nil
}

// RemoveDevice remove device instance
func (d *DevPanel) RemoveDevice(deviceID string) error {
	d.serviceMutex.Lock()
	dev := d.devices[deviceID]
	cancelFunc := d.deviceMuxs[deviceID]
	delete(d.devices, deviceID)
	delete(d.deviceMuxs, deviceID)
	d.serviceMutex.Unlock()

	if cancelFunc != nil {
		cancelFunc()
	}
	return stopCustomizedDevice(dev, deviceID)
}

// WriteDevice write value to the device
func (d *DevPanel) WriteDevice(deviceMethodName, deviceID, propertyName, data string) error {
	var dataType string
	var deviceproperty common.DeviceProperty
	var client *driver.CustomizedClient
	d.serviceMutex.RLock()
	dev, ok := d.devices[deviceID]
	if !ok || dev == nil {
		d.serviceMutex.RUnlock()
		return fmt.Errorf("not found device %s", deviceID)
	}
	client = dev.CustomizedClient

	deviceMethodMap := make(map[string][]string)

	// get all deviceMethod of the device
	for _, method := range dev.Instance.Methods {
		deviceMethodMap[method.Name] = append(deviceMethodMap[method.Name], method.PropertyNames...)
	}
	// Determine whether the called device method exists
	propertyNames, ok := deviceMethodMap[deviceMethodName]
	if !ok {
		d.serviceMutex.RUnlock()
		return fmt.Errorf("device=%s property=%s deviceMethod name %s does not exist in device instance", deviceID, propertyName, deviceMethodName)
	}
	// Determine whether the device property to be written is in the list defined by the device method
	flag := false
	for _, name := range propertyNames {
		if name == propertyName {
			flag = true
			break
		}
	}
	if !flag {
		d.serviceMutex.RUnlock()
		return fmt.Errorf("device=%s property=%s is not in the list defined by devicemethod %s", deviceID, propertyName, deviceMethodName)
	}
	// Determine whether the device property to be written is in the device instance
	flag = false
	for _, property := range dev.Instance.Properties {
		if property.PropertyName != propertyName {
			continue
		}
		dataType = property.PProperty.DataType
		deviceproperty = property
		flag = true
		break
	}
	d.serviceMutex.RUnlock()
	if !flag {
		return fmt.Errorf("device=%s property=%s not found in device instance", deviceID, propertyName)
	}
	if client == nil {
		return fmt.Errorf("device=%s property=%s customized client is nil", deviceID, propertyName)
	}
	klog.V(2).Infof("start writing values %v to device %s property %s", data, deviceID, propertyName)
	writeData, err := common.Convert(strings.ToLower(dataType), data)
	if err != nil {
		return fmt.Errorf("device=%s property=%s conversion failed, datatype is %s, data is %s: %w", deviceID, propertyName, strings.ToLower(dataType), data, err)
	}
	var visitorConfig driver.VisitorConfig
	err = json.Unmarshal(deviceproperty.Visitors, &visitorConfig)
	if err != nil {
		return fmt.Errorf("device=%s property=%s unmarshal visitor config failed: %w", deviceID, propertyName, err)
	}

	err = client.DeviceDataWrite(&visitorConfig, deviceMethodName, propertyName, writeData)
	if err != nil {
		return fmt.Errorf("device=%s property=%s write failed: %w", deviceID, propertyName, err)
	}
	return nil
}

// stopDev stop device and goroutine
func (d *DevPanel) stopDev(dev *driver.CustomizedDev, id string) error {
	d.serviceMutex.Lock()
	cancelFunc, ok := d.deviceMuxs[id]
	if ok {
		delete(d.deviceMuxs, id)
	}
	d.serviceMutex.Unlock()
	if !ok {
		return fmt.Errorf("can not find device %s from device muxs", id)
	}
	cancelFunc()
	return stopCustomizedDevice(dev, id)
}

func stopCustomizedDevice(dev *driver.CustomizedDev, id string) error {
	if dev == nil {
		return nil
	}
	if dev.CustomizedClient == nil {
		return nil
	}
	err := dev.CustomizedClient.StopDevice()
	if err != nil {
		return fmt.Errorf("stop device %s error: %w", id, err)
	}
	return nil
}

// GetModel if the model exists, return device model
func (d *DevPanel) GetModel(modelID string) (common.DeviceModel, error) {
	d.serviceMutex.RLock()
	defer d.serviceMutex.RUnlock()
	if model, ok := d.models[modelID]; ok {
		return model, nil
	}
	return common.DeviceModel{}, fmt.Errorf("deviceModel %s not found", modelID)
}

// UpdateModel update device model
func (d *DevPanel) UpdateModel(model *common.DeviceModel) {
	d.serviceMutex.Lock()
	d.models[model.ID] = *model
	d.serviceMutex.Unlock()
}

// RemoveModel remove device model
func (d *DevPanel) RemoveModel(modelID string) {
	d.serviceMutex.Lock()
	delete(d.models, modelID)
	d.serviceMutex.Unlock()
}

// GetTwinResult Get twin's value and data type
func (d *DevPanel) GetTwinResult(deviceID string, twinName string) (string, string, error) {
	d.serviceMutex.RLock()
	dev, ok := d.devices[deviceID]
	if !ok || dev == nil {
		d.serviceMutex.RUnlock()
		return "", "", fmt.Errorf("not found device %s", deviceID)
	}
	twins := append([]common.Twin(nil), dev.Instance.Twins...)
	client := dev.CustomizedClient
	d.serviceMutex.RUnlock()
	if client == nil {
		return "", "", fmt.Errorf("device=%s customized client is nil", deviceID)
	}
	var res string
	var dataType string
	for _, twin := range twins {
		if twinName != "" && twin.PropertyName != twinName {
			continue
		}
		if twin.Property == nil {
			return "", "", fmt.Errorf("device=%s property=%s twin property is nil", deviceID, twin.PropertyName)
		}
		var visitorConfig driver.VisitorConfig
		err := json.Unmarshal(twin.Property.Visitors, &visitorConfig)
		if err != nil {
			return "", "", fmt.Errorf("device=%s property=%s unmarshal visitor config failed: %w", deviceID, twin.PropertyName, err)
		}
		data, err := client.GetDeviceData(&visitorConfig)
		if err != nil {
			return "", "", fmt.Errorf("device=%s property=%s get device data failed: %w", deviceID, twin.PropertyName, err)
		}
		res, err = common.ConvertToString(data)
		if err != nil {
			return "", "", fmt.Errorf("device=%s property=%s convert value failed: %w", deviceID, twin.PropertyName, err)
		}
		dataType = twin.Property.PProperty.DataType
	}
	return res, dataType, nil
}

// GetDeviceMethod get method and property dataType of device
func (d *DevPanel) GetDeviceMethod(deviceID string) (map[string][]string, map[string]string, error) {
	klog.V(2).Infof("starting get method and property dataType of device %s", deviceID)
	d.serviceMutex.RLock()
	defer d.serviceMutex.RUnlock()
	found, ok := d.devices[deviceID]
	if !ok || found == nil {
		return nil, nil, fmt.Errorf("device %s not found", deviceID)
	}

	deviceMethodMap := make(map[string][]string)
	propertyTypeMap := make(map[string]string)

	// get all deviceMethod of the device
	for _, method := range found.Instance.Methods {
		deviceMethodMap[method.Name] = append(deviceMethodMap[method.Name], method.PropertyNames...)
	}

	// get all deviceProperty type of the device
	for _, property := range found.Instance.Properties {
		propertyTypeMap[property.Name] = strings.ToLower(property.PProperty.DataType) // The original data type is an uppercase form such as INT FLOAT and needs to be converted.
	}
	return deviceMethodMap, propertyTypeMap, nil
}
