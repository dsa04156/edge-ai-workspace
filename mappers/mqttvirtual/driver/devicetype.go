package driver

import (
	"sync"

	mqtt "github.com/eclipse/paho.mqtt.golang"
	"github.com/kubeedge/mapper-framework/pkg/common"
)

// CustomizedDev is the customized device configuration and client information.
type CustomizedDev struct {
	Instance         common.DeviceInstance
	CustomizedClient *CustomizedClient
}

type CustomizedClient struct {
	deviceMutex sync.Mutex
	Client      mqtt.Client
	LatestValues map[string]interface{}
	Events      chan map[string]interface{}
	ProtocolConfig
}

type ProtocolConfig struct {
	ProtocolName string `json:"protocolName"`
	ConfigData   `json:"configData"`
}

type ConfigData struct {
	Broker   string `json:"broker"`
	SubTopic string `json:"subTopic"`
	PubTopic string `json:"pubTopic"`
	ClientID string `json:"clientID"`
	Username string `json:"username"`
	Password string `json:"password"`
	QoS      byte   `json:"qos"`
}

type VisitorConfig struct {
	ProtocolName      string `json:"protocolName"`
	VisitorConfigData `json:"configData"`
}

type VisitorConfigData struct {
	DataType string `json:"dataType"`
	JsonKey  string `json:"jsonKey"`
}
