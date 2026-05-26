package influxdb2

import (
	"os"
	"testing"
)

func TestInfluxBatchDefaults(t *testing.T) {
	t.Setenv("INFLUXDB_BATCH_SIZE", "")
	t.Setenv("INFLUXDB_BATCH_FLUSH_SECONDS", "")

	if got := influxBatchSize(); got != 1000 {
		t.Fatalf("expected default batch size 1000, got %d", got)
	}
	if got := influxFlushInterval(); got != 30000 {
		t.Fatalf("expected default flush interval 30000ms, got %d", got)
	}
}

func TestInfluxBatchEnvOverrides(t *testing.T) {
	t.Setenv("INFLUXDB_BATCH_SIZE", "25")
	t.Setenv("INFLUXDB_BATCH_FLUSH_SECONDS", "7")

	if got := influxBatchSize(); got != 25 {
		t.Fatalf("expected env batch size 25, got %d", got)
	}
	if got := influxFlushInterval(); got != 7000 {
		t.Fatalf("expected env flush interval 7000ms, got %d", got)
	}
}

func TestEnvUintRejectsInvalidValues(t *testing.T) {
	os.Setenv("BAD_UINT", "0")
	if got := envUint("BAD_UINT", 12); got != 12 {
		t.Fatalf("expected fallback for zero value, got %d", got)
	}

	os.Setenv("BAD_UINT", "not-a-number")
	if got := envUint("BAD_UINT", 12); got != 12 {
		t.Fatalf("expected fallback for invalid value, got %d", got)
	}
}
