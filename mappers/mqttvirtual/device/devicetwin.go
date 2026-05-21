package device

import (
	"context"
	"fmt"
	"strings"
	"time"

	"k8s.io/klog/v2"

	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mqttvirtual/driver"
	"github.com/kubeedge/mqttvirtual/status"
)

type TwinData struct {
	DeviceName      string
	DeviceNamespace string
	Client          *driver.CustomizedClient
	Name            string
	Type            string
	ObservedDesired common.TwinProperty
	VisitorConfig   *driver.VisitorConfig
	Topic           string
	Results         interface{}
	CollectCycle    time.Duration
	ReportToCloud   bool
}

func (td *TwinData) GetPayLoad() ([]byte, error) {
	var err error
	td.VisitorConfig.VisitorConfigData.DataType = strings.ToLower(td.VisitorConfig.VisitorConfigData.DataType)
	td.Results, err = td.Client.GetDeviceData(td.VisitorConfig)
	if err != nil {
		return nil, fmt.Errorf("get device data failed: %v", err)
	}
	sData, err := common.ConvertToString(td.Results)
	if err != nil {
		klog.Errorf("Failed to convert %s %s value as string : %v", td.DeviceName, td.Name, err)
		return nil, err
	}
	if len(sData) > 30 {
		klog.V(4).Infof("Get %s : %s ,value is %s......", td.DeviceName, td.Name, sData[:30])
	} else {
		klog.V(4).Infof("Get %s : %s ,value is %s", td.DeviceName, td.Name, sData)
	}
	var payload []byte
	if strings.Contains(td.Topic, "$hw") {
		if payload, err = common.CreateMessageTwinUpdate(td.Name, td.Type, sData, td.ObservedDesired.Value); err != nil {
			return nil, fmt.Errorf("create message twin update failed: %v", err)
		}
	} else {
		if payload, err = common.CreateMessageData(td.Name, td.Type, sData); err != nil {
			return nil, fmt.Errorf("create message data failed: %v", err)
		}
	}
	return payload, nil
}

func (td *TwinData) PushToEdgeCore() {
	summary, err := td.BuildStatusSummary()
	if err != nil {
		klog.Errorf("twindata %s summary build failed, err: %s", td.Name, err)
		return
	}
	if err := (status.DMIReporter{}).Report(context.Background(), summary); err != nil {
		klog.Errorf("fail to report device status summary of %s with err: %+v", td.DeviceName, err)
	}
}

func (td *TwinData) BuildStatusSummary() (status.Summary, error) {
	if td == nil {
		return status.Summary{}, fmt.Errorf("twin data is nil")
	}
	if !status.IsSummaryField(td.Name) {
		return status.Summary{}, fmt.Errorf("property %q is not allowed in DeviceStatus summary", td.Name)
	}
	value, err := td.GetStringValue()
	if err != nil {
		return status.Summary{}, err
	}
	return status.Summary{
		DeviceName:      td.DeviceName,
		DeviceNamespace: td.DeviceNamespace,
		Source:          "mapper-framework",
		Values: map[string]string{
			td.Name: value,
		},
	}, nil
}

func (td *TwinData) GetStringValue() (string, error) {
	if td == nil || td.Client == nil || td.VisitorConfig == nil {
		return "", fmt.Errorf("twin data/client/visitor is nil")
	}
	td.VisitorConfig.VisitorConfigData.DataType = strings.ToLower(td.VisitorConfig.VisitorConfigData.DataType)
	results, err := td.Client.GetDeviceData(td.VisitorConfig)
	if err != nil {
		return "", fmt.Errorf("get device data failed: %v", err)
	}
	sData, err := common.ConvertToString(results)
	if err != nil {
		return "", err
	}
	return sData, nil
}

func (td *TwinData) Run(ctx context.Context) {
	if !td.ReportToCloud {
		return
	}
	if td.CollectCycle == 0 {
		td.CollectCycle = common.DefaultCollectCycle
	}
	ticker := time.NewTicker(td.CollectCycle)
	for {
		select {
		case <-ticker.C:
			td.PushToEdgeCore()
		case <-ctx.Done():
			return
		}
	}
}
