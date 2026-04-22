package main

import (
	"errors"
	"os"
	"time"

	"k8s.io/klog/v2"

	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mapper-framework/pkg/config"
	"github.com/kubeedge/mapper-framework/pkg/grpcclient"
	"github.com/kubeedge/mapper-framework/pkg/grpcserver"
	"github.com/kubeedge/mapper-framework/pkg/httpserver"
	"github.com/kubeedge/mqttvirtual/device"
)

func main() {
	var err error
	var c *config.Config

	klog.InitFlags(nil)
	defer klog.Flush()

	if c, err = config.Parse(); err != nil {
		klog.Fatal(err)
	}
	klog.Infof("config: %+v", c)

	panel := device.NewDevPanel()

	grpcServer := grpcserver.NewServer(
		grpcserver.Config{
			SockPath: c.GrpcServer.SocketPath,
			Protocol: common.ProtocolCustomized,
		},
		panel,
	)
	defer grpcServer.Stop()
	go func() {
		if err := grpcServer.Start(); err != nil {
			klog.Fatal(err)
		}
	}()
	if err := waitForSocket(c.GrpcServer.SocketPath, 3*time.Second); err != nil {
		klog.Fatal(err)
	}

	klog.Infoln("Mapper will register to edgecore")
	deviceList, deviceModelList, err := grpcclient.RegisterMapper(true)
	if err != nil {
		klog.Fatal(err)
	}
	klog.Infoln("Mapper register finished")

	err = panel.DevInit(deviceList, deviceModelList)
	if err != nil && !errors.Is(err, device.ErrEmptyData) {
		klog.Fatal(err)
	}
	klog.Infoln("devInit finished")
	go panel.DevStart()

	// start http server
	httpServer := httpserver.NewRestServer(panel, c.Common.HTTPPort)
	go httpServer.StartServer()
	select {}
}

func waitForSocket(sockPath string, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if _, err := os.Stat(sockPath); err == nil {
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	return errors.New("mapper grpc socket was not created before registration")
}
