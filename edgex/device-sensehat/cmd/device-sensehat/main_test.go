package main

import (
	"strings"
	"testing"
)

func TestServiceIdentityUsesDefaultWhenOverrideIsMissingOrBlank(t *testing.T) {
	t.Setenv(serviceNameEnv, "")

	got, err := serviceIdentity()

	if err != nil {
		t.Fatalf("serviceIdentity returned error: %v", err)
	}
	if got != serviceName {
		t.Fatalf("serviceIdentity = %q, want %q", got, serviceName)
	}
}

func TestServiceIdentityAcceptsRuntimeSpecificDNSLabel(t *testing.T) {
	t.Setenv(serviceNameEnv, "device-sensehat-raspi-02")

	got, err := serviceIdentity()

	if err != nil {
		t.Fatalf("serviceIdentity returned error: %v", err)
	}
	if got != "device-sensehat-raspi-02" {
		t.Fatalf("serviceIdentity = %q", got)
	}
}

func TestServiceIdentityRejectsUnsafeRuntimeNames(t *testing.T) {
	for _, value := range []string{
		"Device-SenseHAT",
		"device/sensehat",
		"-device-sensehat",
		strings.Repeat("a", 64),
	} {
		t.Run(value, func(t *testing.T) {
			t.Setenv(serviceNameEnv, value)
			if _, err := serviceIdentity(); err == nil {
				t.Fatalf("serviceIdentity accepted unsafe value %q", value)
			}
		})
	}
}
