package driver

import (
	"encoding/json"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/kubeedge/mapper-framework/pkg/common"
)

func NewClient(protocol ProtocolConfig) (*CustomizedClient, error) {
	client := &CustomizedClient{
		ProtocolConfig: protocol,
		deviceMutex:    sync.Mutex{},
		LatestValues:   make(map[string]interface{}),
		Events:         make(chan map[string]interface{}, 32),
	}
	return client, nil
}

func (c *CustomizedClient) InitDevice() error {
	log.Printf("InitDevice protocol=%+v", c.ProtocolConfig)
	if strings.TrimSpace(c.ConfigData.Broker) == "" {
		return fmt.Errorf("broker is empty")
	}
	if strings.TrimSpace(c.ConfigData.SubTopic) == "" {
		return fmt.Errorf("subTopic is empty")
	}
	if strings.TrimSpace(c.ConfigData.ClientID) == "" {
		c.ConfigData.ClientID = "mqttvirtual-client"
	}
	if strings.ContainsAny(c.ConfigData.SubTopic, "+#") {
		return fmt.Errorf("wildcard subTopic %q is not supported by mqttvirtual demo mapper; use one topic per device", c.ConfigData.SubTopic)
	}
	if strings.TrimSpace(c.ConfigData.PubTopic) != "" && c.ConfigData.PubTopic == c.ConfigData.SubTopic {
		log.Printf("warning: pubTopic and subTopic are identical (%s); command payloads may be re-consumed as telemetry", c.ConfigData.SubTopic)
	}

	opts := mqtt.NewClientOptions()
	opts.AddBroker(c.ConfigData.Broker)
	opts.SetClientID(c.ConfigData.ClientID)
	opts.SetAutoReconnect(true)
	opts.SetOrderMatters(false)

	if c.ConfigData.Username != "" {
		opts.SetUsername(c.ConfigData.Username)
	}
	if c.ConfigData.Password != "" {
		opts.SetPassword(c.ConfigData.Password)
	}
	opts.OnConnectionLost = func(_ mqtt.Client, err error) {
		log.Printf("mqtt connection lost broker=%s subTopic=%s err=%v", c.ConfigData.Broker, c.ConfigData.SubTopic, err)
	}

	opts.OnConnect = func(mc mqtt.Client) {
		log.Printf("mqtt connected broker=%s subTopic=%s", c.ConfigData.Broker, c.ConfigData.SubTopic)

		token := mc.Subscribe(c.ConfigData.SubTopic, c.ConfigData.QoS, func(_ mqtt.Client, msg mqtt.Message) {
			var payload map[string]interface{}
			if err := json.Unmarshal(msg.Payload(), &payload); err != nil {
				log.Printf("invalid mqtt payload: %v", err)
				return
			}

			log.Printf("mqtt payload received: %+v", payload)
			c.applyPayload(payload)
		})
		token.Wait()
		if token.Error() != nil {
			log.Printf("subscribe failed: %v", token.Error())
		}
	}

	client := mqtt.NewClient(opts)
	token := client.Connect()
	token.Wait()
	if token.Error() != nil {
		return fmt.Errorf("mqtt connect failed: %w", token.Error())
	}

	c.Client = client
	return nil
}

func (c *CustomizedClient) applyPayload(payload map[string]interface{}) {
	payloadCopy := make(map[string]interface{}, len(payload))

	c.deviceMutex.Lock()
	for k, v := range payload {
		c.LatestValues[k] = v
		payloadCopy[k] = v
	}
	c.LastSeenAt = time.Now()
	c.HasTelemetry = true
	c.deviceMutex.Unlock()

	c.enqueueEvent(payloadCopy)
}

func (c *CustomizedClient) enqueueEvent(payload map[string]interface{}) {
	select {
	case c.Events <- payload:
		return
	default:
	}

	select {
	case <-c.Events:
	default:
	}

	select {
	case c.Events <- payload:
	default:
		log.Printf("mqtt event dropped after replacing stale buffered event")
	}
}

func (c *CustomizedClient) GetDeviceData(visitor *VisitorConfig) (interface{}, error) {
	log.Printf("GetDeviceData called, visitor=%+v", visitor)

	if visitor == nil {
		return nil, fmt.Errorf("visitor is nil")
	}
	if visitor.JsonKey == "" {
		return nil, fmt.Errorf("visitor jsonKey is empty")
	}

	c.deviceMutex.Lock()
	defer c.deviceMutex.Unlock()

	v, ok := c.LatestValues[visitor.JsonKey]
	if !ok {
		return nil, fmt.Errorf("no cached value for key=%s", visitor.JsonKey)
	}
	log.Printf("GetDeviceData return key=%s value=%v", visitor.JsonKey, v)

	return v, nil
}

func (c *CustomizedClient) DeviceDataWrite(visitor *VisitorConfig, deviceMethodName string, propertyName string, data interface{}) error {
	key := propertyName
	if visitor != nil && visitor.JsonKey != "" {
		key = visitor.JsonKey
	}
	if key == "" {
		key = "value"
	}

	if c.Client == nil {
		c.setLatestValue(key, data)
		return nil
	}
	if !c.Client.IsConnectionOpen() {
		return fmt.Errorf("mqtt client is not connected")
	}
	if strings.TrimSpace(c.ConfigData.PubTopic) == "" {
		c.setLatestValue(key, data)
		return nil
	}

	payload := map[string]interface{}{
		key: data,
	}

	b, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal publish payload failed: %w", err)
	}

	token := c.Client.Publish(c.ConfigData.PubTopic, c.ConfigData.QoS, false, b)
	token.Wait()
	if token.Error() != nil {
		return fmt.Errorf("publish failed: %w", token.Error())
	}

	c.setLatestValue(key, data)
	log.Printf("mqtt publish topic=%s payload=%s", c.ConfigData.PubTopic, string(b))
	return nil
}

func (c *CustomizedClient) SetDeviceData(data interface{}, visitor *VisitorConfig) error {
	if visitor == nil {
		return fmt.Errorf("visitor is nil")
	}
	if visitor.JsonKey == "" {
		return fmt.Errorf("visitor jsonKey is empty")
	}

	c.deviceMutex.Lock()
	c.LatestValues[visitor.JsonKey] = data
	c.deviceMutex.Unlock()

	return nil
}

func (c *CustomizedClient) EnsureDeviceData(data interface{}, visitor *VisitorConfig) error {
	if visitor == nil {
		return fmt.Errorf("visitor is nil")
	}
	if visitor.JsonKey == "" {
		return fmt.Errorf("visitor jsonKey is empty")
	}

	c.deviceMutex.Lock()
	if _, ok := c.LatestValues[visitor.JsonKey]; !ok {
		c.LatestValues[visitor.JsonKey] = data
	}
	c.deviceMutex.Unlock()

	return nil
}

func (c *CustomizedClient) setLatestValue(key string, data interface{}) {
	if key == "" {
		return
	}

	c.deviceMutex.Lock()
	c.LatestValues[key] = data
	c.deviceMutex.Unlock()
}

func (c *CustomizedClient) StopDevice() error {
	if c.Client != nil && c.Client.IsConnectionOpen() {
		c.Client.Disconnect(250)
	}
	return nil
}

func (c *CustomizedClient) GetDeviceStates() (string, error) {
	if c.Client == nil {
		return common.DeviceStatusDisCONN, nil
	}
	if !c.Client.IsConnectionOpen() {
		return common.DeviceStatusDisCONN, nil
	}

	c.deviceMutex.Lock()
	lastSeenAt := c.LastSeenAt
	hasTelemetry := c.HasTelemetry
	c.deviceMutex.Unlock()

	if !hasTelemetry {
		return common.DeviceStatusUnknown, nil
	}

	offlineAfter := time.Duration(c.ConfigData.OfflineAfterMs) * time.Millisecond
	if offlineAfter <= 0 {
		offlineAfter = 15 * time.Second
	}
	if time.Since(lastSeenAt) > offlineAfter {
		return common.DeviceStatusOffline, nil
	}
	return common.DeviceStatusOnline, nil
}
