package main

import (
	"github.com/dsa04156/edge-ai-workspace/edgex/device-serial/internal/driver"
	"github.com/edgexfoundry/device-sdk-go/v4/pkg/startup"
)

const (
	serviceName    = "device-serial-jetson"
	serviceVersion = "0.1.0"
)

func main() {
	startup.Bootstrap(serviceName, serviceVersion, driver.NewDriver())
}
