package telemetry

import (
	"context"
	"time"

	"k8s.io/klog/v2"
)

// Sample is a debug/internal compatibility raw telemetry schema retained for
// disconnected tests and migration experiments only. It is not the production
// raw telemetry path.
//
// MapperFramework must not be expanded into the production raw telemetry export
// engine; EdgeX or another separate ingestion plane owns that path.
type Sample struct {
	DeviceID   string                 `json:"device_id"`
	DeviceType string                 `json:"device_type"`
	NodeName   string                 `json:"node_name"`
	Source     string                 `json:"source"`
	Protocol   string                 `json:"protocol"`
	Timestamp  time.Time              `json:"timestamp"`
	Tags       map[string]string      `json:"tags"`
	Fields     map[string]interface{} `json:"fields"`
}

// Sink is intentionally not wired into the main mapper path.
//
// WARNING: do not add MQTTTelemetrySink, CollectorTelemetrySink, InfluxDBSink,
// KafkaSink, or other production raw telemetry sinks under MapperFramework.
type Sink interface {
	Export(ctx context.Context, sample Sample) error
}

type SinkFunc func(context.Context, Sample) error

func (fn SinkFunc) Export(ctx context.Context, sample Sample) error {
	return fn(ctx, sample)
}

// LogSink is a debug/internal compatibility sink for development and
// disconnected tests. It is not a production raw telemetry exporter.
type LogSink struct{}

func (LogSink) Export(ctx context.Context, sample Sample) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}
	klog.V(2).Infof("debug/internal telemetry sample exported to log sink device_id=%s device_type=%s source=%s protocol=%s tags=%v fields=%v",
		sample.DeviceID, sample.DeviceType, sample.Source, sample.Protocol, sample.Tags, sample.Fields)
	return nil
}
