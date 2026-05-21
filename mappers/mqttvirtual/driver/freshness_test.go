package driver

import (
	"testing"
	"time"
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
