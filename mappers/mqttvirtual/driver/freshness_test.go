package driver

import (
	"testing"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/kubeedge/mapper-framework/pkg/common"
)

func TestHasFreshTelemetryRejectsStaleCachedValue(t *testing.T) {
	client := &CustomizedClient{
		LatestValues:   map[string]interface{}{"value": 23.5},
		LastSeenAt:     time.Now().Add(-20 * time.Second),
		HasTelemetry:   true,
		ProtocolConfig: ProtocolConfig{ConfigData: ConfigData{OfflineAfterMs: 15000}},
	}

	if client.HasFreshTelemetry() {
		t.Fatalf("stale cached MQTT value must not be treated as fresh telemetry")
	}
}

func TestHasFreshTelemetryAcceptsRecentMessage(t *testing.T) {
	client := &CustomizedClient{
		LatestValues:   map[string]interface{}{"value": 23.5},
		LastSeenAt:     time.Now().Add(-2 * time.Second),
		HasTelemetry:   true,
		ProtocolConfig: ProtocolConfig{ConfigData: ConfigData{OfflineAfterMs: 15000}},
	}

	if !client.HasFreshTelemetry() {
		t.Fatalf("recent MQTT message should be treated as fresh telemetry")
	}
}

func TestHasFreshTelemetryRejectsNoTelemetry(t *testing.T) {
	client := &CustomizedClient{}

	if client.HasFreshTelemetry() {
		t.Fatalf("client with no received MQTT message must not be fresh")
	}
}

func TestGetDeviceStatusSummaryStateReportsTelemetryMissing(t *testing.T) {
	client := &CustomizedClient{Client: fakeMQTTClient{open: true}}

	state, err := client.GetDeviceStatusSummaryState()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state != "telemetry_missing" {
		t.Fatalf("state=%q, want telemetry_missing", state)
	}
}

func TestGetDeviceStatusSummaryStateReportsTelemetryStale(t *testing.T) {
	client := &CustomizedClient{
		Client:         fakeMQTTClient{open: true},
		LastSeenAt:     time.Now().Add(-20 * time.Second),
		HasTelemetry:   true,
		ProtocolConfig: ProtocolConfig{ConfigData: ConfigData{OfflineAfterMs: 15000}},
	}

	state, err := client.GetDeviceStatusSummaryState()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state != "telemetry_stale" {
		t.Fatalf("state=%q, want telemetry_stale", state)
	}
}

func TestGetDeviceStatusSummaryStateReportsOnlineWhenTelemetryFresh(t *testing.T) {
	client := &CustomizedClient{
		Client:         fakeMQTTClient{open: true},
		LastSeenAt:     time.Now().Add(-2 * time.Second),
		HasTelemetry:   true,
		ProtocolConfig: ProtocolConfig{ConfigData: ConfigData{OfflineAfterMs: 15000}},
	}

	state, err := client.GetDeviceStatusSummaryState()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state != common.DeviceStatusOnline {
		t.Fatalf("state=%q, want %q", state, common.DeviceStatusOnline)
	}
}

func TestGetDeviceStatusSummaryStateReportsDisconnectedWhenMQTTClosed(t *testing.T) {
	client := &CustomizedClient{Client: fakeMQTTClient{open: false}}

	state, err := client.GetDeviceStatusSummaryState()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if state != common.DeviceStatusDisCONN {
		t.Fatalf("state=%q, want %q", state, common.DeviceStatusDisCONN)
	}
}

type fakeMQTTClient struct{ open bool }

func (f fakeMQTTClient) IsConnected() bool                                      { return f.open }
func (f fakeMQTTClient) IsConnectionOpen() bool                                 { return f.open }
func (f fakeMQTTClient) Connect() mqtt.Token                                    { return nil }
func (f fakeMQTTClient) Disconnect(uint)                                        {}
func (f fakeMQTTClient) Publish(string, byte, bool, interface{}) mqtt.Token     { return nil }
func (f fakeMQTTClient) Subscribe(string, byte, mqtt.MessageHandler) mqtt.Token { return nil }
func (f fakeMQTTClient) SubscribeMultiple(map[string]byte, mqtt.MessageHandler) mqtt.Token {
	return nil
}
func (f fakeMQTTClient) Unsubscribe(...string) mqtt.Token        { return nil }
func (f fakeMQTTClient) AddRoute(string, mqtt.MessageHandler)    {}
func (f fakeMQTTClient) OptionsReader() mqtt.ClientOptionsReader { return mqtt.ClientOptionsReader{} }
