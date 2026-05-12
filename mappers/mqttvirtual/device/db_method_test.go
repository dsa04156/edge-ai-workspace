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
