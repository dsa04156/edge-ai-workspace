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

func TestShouldPersistPropertyToDBSkipsRawTelemetry(t *testing.T) {
	rawProperties := []string{"raw", "value", "x", "y", "z", "temperature", "humidity", "vibration"}
	for _, name := range rawProperties {
		if shouldPersistPropertyToDB(name) {
			t.Fatalf("expected raw telemetry property %q not to be persisted by mapper", name)
		}
	}
}

func TestShouldPersistPropertyToDBAllowsOperationalLiveness(t *testing.T) {
	allowed := []string{"health", "severity", "alarm_latched", "status", "command_state"}
	for _, name := range allowed {
		if !shouldPersistPropertyToDB(name) {
			t.Fatalf("expected operational property %q to remain mapper-persistable", name)
		}
	}
}
