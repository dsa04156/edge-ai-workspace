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
