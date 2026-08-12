package main

import (
	"fmt"
	"log"
	"os"
	"regexp"
	"strings"

	"github.com/dsa04156/edge-ai-workspace/edgex/device-sensehat/internal/driver"
	"github.com/edgexfoundry/device-sdk-go/v4/pkg/startup"
)

const (
	serviceName    = "device-sensehat-raspi"
	serviceVersion = "0.1.0"
	serviceNameEnv = "EDGEX_SERVICE_NAME"
)

var serviceNamePattern = regexp.MustCompile(`^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$`)

func serviceIdentity() (string, error) {
	raw := os.Getenv(serviceNameEnv)
	candidate := strings.TrimSpace(raw)
	if candidate == "" {
		return serviceName, nil
	}
	if candidate != raw || len(candidate) > 63 || !serviceNamePattern.MatchString(candidate) {
		return "", fmt.Errorf("%s must be a valid DNS label of at most 63 characters", serviceNameEnv)
	}
	return candidate, nil
}

func main() {
	runtimeServiceName, err := serviceIdentity()
	if err != nil {
		log.Fatal(err)
	}
	startup.Bootstrap(runtimeServiceName, serviceVersion, driver.NewDriver())
}
