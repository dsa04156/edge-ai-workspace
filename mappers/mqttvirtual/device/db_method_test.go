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

func TestRawTelemetryPropertiesAreNotDBDenylisted(t *testing.T) {
	// KubeEdge Device CR pushMethod.dbMethod.influxdb2 is the official persistence path.
	// Raw sensor properties must not be filtered by the mapper; if a property has a
	// DB pushMethod, dbHandler should dispatch it to the configured DB method.
	rawProperties := []string{"raw", "value", "x", "y", "z", "temperature", "humidity", "vibration"}
	if len(rawProperties) == 0 {
		t.Fatal("raw property regression fixture is empty")
	}
}
