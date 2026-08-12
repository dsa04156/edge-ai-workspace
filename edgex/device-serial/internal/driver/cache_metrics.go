package driver

import (
	"fmt"
	"sync"

	localcache "github.com/dsa04156/edge-ai-workspace/edgex/local-data-cache"
	bootstrapInterfaces "github.com/edgexfoundry/go-mod-bootstrap/v4/bootstrap/interfaces"
	gometrics "github.com/rcrowley/go-metrics"
)

const (
	localDataCacheSamplesMetric        = "LocalDataCacheSamples"
	localDataCacheSeriesMetric         = "LocalDataCacheSeries"
	localDataCacheAllocatedBytesMetric = "LocalDataCacheAllocatedBytes"
	localDataCacheEvictionsMetric      = "LocalDataCacheEvictions"
)

type localDataCacheMetrics struct {
	mu             sync.Mutex
	samples        gometrics.Gauge
	series         gometrics.Gauge
	allocatedBytes gometrics.Gauge
	evictions      gometrics.Counter
	lastEvictions  int64
}

func newLocalDataCacheMetrics() *localDataCacheMetrics {
	return &localDataCacheMetrics{
		samples:        gometrics.NewGauge(),
		series:         gometrics.NewGauge(),
		allocatedBytes: gometrics.NewGauge(),
		evictions:      gometrics.NewCounter(),
	}
}

func (metrics *localDataCacheMetrics) register(
	manager bootstrapInterfaces.MetricsManager,
) error {
	if manager == nil {
		return nil
	}
	registrations := []struct {
		name string
		item interface{}
	}{
		{name: localDataCacheSamplesMetric, item: metrics.samples},
		{name: localDataCacheSeriesMetric, item: metrics.series},
		{name: localDataCacheAllocatedBytesMetric, item: metrics.allocatedBytes},
		{name: localDataCacheEvictionsMetric, item: metrics.evictions},
	}
	for _, registration := range registrations {
		if err := manager.Register(registration.name, registration.item, nil); err != nil {
			return fmt.Errorf("register metric %s: %w", registration.name, err)
		}
	}
	return nil
}

func (metrics *localDataCacheMetrics) observe(stats localcache.Stats) {
	metrics.mu.Lock()
	defer metrics.mu.Unlock()

	metrics.samples.Update(int64(stats.Samples))
	metrics.series.Update(int64(stats.Series))
	metrics.allocatedBytes.Update(stats.AllocatedBytes)
	totalEvictions := stats.Evictions.Total()
	if totalEvictions > metrics.lastEvictions {
		metrics.evictions.Inc(totalEvictions - metrics.lastEvictions)
		metrics.lastEvictions = totalEvictions
	}
}
