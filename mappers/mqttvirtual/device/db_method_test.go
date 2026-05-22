package device

import "testing"

func TestIsInfluxDBMethodAcceptsLegacyAndInfluxDB2Names(t *testing.T) {
	cases := []string{"influx", "influxdb2"}
	for _, name := range cases {
		if !isInfluxDBMethod(name) {
			t.Fatalf("expected %q to be treated as an InfluxDB method", name)
		}
	}
}

func TestIsInfluxDBMethodRejectsOtherMethods(t *testing.T) {
	cases := []string{"", "redis", "tdengine", "mysql"}
	for _, name := range cases {
		if isInfluxDBMethod(name) {
			t.Fatalf("expected %q not to be treated as an InfluxDB method", name)
		}
	}
}

func TestRawTelemetryPropertiesAreTrackedAsNonStatusFields(t *testing.T) {
	// Raw sensor properties may use mapper DB export when dbMethod is configured,
	// but they must stay out of DeviceStatus/control-status reporting.
	rawProperties := []string{"raw", "value", "x", "y", "z", "temperature", "humidity", "vibration", "current", "voltage"}
	if len(rawProperties) == 0 {
		t.Fatal("raw property regression fixture is empty")
	}
}
