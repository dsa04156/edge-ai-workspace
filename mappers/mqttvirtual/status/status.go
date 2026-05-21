package status

import (
	"context"
	"encoding/json"
	"fmt"

	dmiapi "github.com/kubeedge/api/apis/dmi/v1beta1"
	"github.com/kubeedge/mapper-framework/pkg/common"
	"github.com/kubeedge/mapper-framework/pkg/grpcclient"
	"github.com/kubeedge/mapper-framework/pkg/util/parse"
)

// Reporter owns the KubeEdge control/status-plane update path.
// It accepts only low-frequency operational summaries, never raw sensor telemetry.
type Reporter interface {
	Report(ctx context.Context, summary Summary) error
}

// Summary is the narrow input contract for KubeEdge DeviceStatus updates.
// Raw sensor values must not be represented here. Raw telemetry ingestion is handled
// by the separate telemetry ingestion plane, not by MapperFramework status reporting.
type Summary struct {
	DeviceName      string
	DeviceNamespace string
	Source          string
	Values          map[string]string
}

// DMIReporter reports summary-only DeviceStatus updates through the KubeEdge DMI API.
type DMIReporter struct{}

func (DMIReporter) Report(ctx context.Context, summary Summary) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	if summary.DeviceName == "" {
		return fmt.Errorf("device status summary device name is empty")
	}

	values := make(map[string]string, len(summary.Values)+1)
	for name, value := range summary.Values {
		values[name] = value
	}
	if summary.Source != "" {
		values["statusSource"] = summary.Source
	}

	twins := make([]*dmiapi.Twin, 0, len(values))
	for name, value := range values {
		if !IsSummaryField(name) {
			return fmt.Errorf("field %q is not allowed in DeviceStatus summary", name)
		}
		payload, err := common.CreateMessageData(name, "string", value)
		if err != nil {
			return fmt.Errorf("create DeviceStatus summary payload for %s failed: %w", name, err)
		}
		var msg common.DeviceTwinUpdate
		if err := json.Unmarshal(payload, &msg); err != nil {
			return fmt.Errorf("unmarshal DeviceStatus summary payload for %s failed: %w", name, err)
		}
		twins = append(twins, parse.ConvMsgTwinToGrpc(msg.Twin)...)
	}
	if len(twins) == 0 {
		return nil
	}

	req := &dmiapi.ReportDeviceStatusRequest{
		DeviceName:      summary.DeviceName,
		DeviceNamespace: summary.DeviceNamespace,
		ReportedDevice:  &dmiapi.DeviceStatus{Twins: twins},
	}
	if err := grpcclient.ReportDeviceStatus(req); err != nil {
		return fmt.Errorf("report DeviceStatus summary for %s failed: %w", summary.DeviceName, err)
	}
	return nil
}

func IsSummaryField(name string) bool {
	_, ok := summaryFields[name]
	return ok
}

func AllowedSummaryFields() map[string]struct{} {
	out := make(map[string]struct{}, len(summaryFields))
	for k, v := range summaryFields {
		out[k] = v
	}
	return out
}

var summaryFields = map[string]struct{}{
	"health":                  {},
	"severity":                {},
	"mapperLastSeen":          {},
	"controlLastSeen":         {},
	"statusLastSeen":          {},
	"statusSource":            {},
	"online":                  {},
	"offline":                 {},
	"control_response":        {},
	"last_control_response":   {},
	"alarm_latched":           {},
	"power":                   {},
	"mode":                    {},
	"sampling_interval":       {},
	"config_version":          {},
	"reported_config_version": {},
	"command_state":           {},
	"last_error_code":         {},
	"last_error_message":      {},
	"temperature_status":      {},
	"humidity_status":         {},
	"vibration_status":        {},
}

var deprecatedSummaryFields = map[string]struct{}{
	"lastSeen":        {},
	"last_seen":       {},
	"telemetryFresh":  {},
	"telemetry_fresh": {},
	"source":          {},
}

func IsDeprecatedSummaryField(name string) bool {
	_, ok := deprecatedSummaryFields[name]
	return ok
}
