package influxdb2

import (
	"os"
	"strings"
	"testing"
)

func TestAddDataErrorDoesNotStopWriteLoop(t *testing.T) {
	content, err := os.ReadFile("handler.go")
	if err != nil {
		t.Fatal(err)
	}

	badPattern := "klog.Errorf(\"influx database add data error: %v\", err)\n\t\t\t\t\treturn"
	if strings.Contains(string(content), badPattern) {
		t.Fatalf("InfluxDB AddData error must not return from the write loop; continue so transient write errors do not kill telemetry writes")
	}
}

func TestInfluxHandlerSkipsStaleCachedTelemetry(t *testing.T) {
	content, err := os.ReadFile("handler.go")
	if err != nil {
		t.Fatal(err)
	}

	text := string(content)
	if !strings.Contains(text, "client.HasFreshTelemetry()") {
		t.Fatalf("InfluxDB handler must check MQTT freshness before writing cached values")
	}
	if !strings.Contains(text, "skip stale cached telemetry") {
		t.Fatalf("InfluxDB handler should log when stale cached telemetry is skipped")
	}
}
