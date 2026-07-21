package driver

import (
	"sort"
	"sync"
	"time"
)

const (
	recentCacheMaxAge     = 10 * time.Minute
	recentCacheMaxSamples = 10_000
	recentDefaultLimit    = 1_000
)

type cachedSample struct {
	Origin    int64  `json:"origin"`
	ValueType string `json:"valueType"`
	Value     int32  `json:"value"`
}

type cacheKey struct {
	deviceName   string
	resourceName string
}

type recentCache struct {
	mu         sync.RWMutex
	maxAge     time.Duration
	maxSamples int
	series     map[cacheKey][]cachedSample
}

func newRecentCache(maxAge time.Duration, maxSamples int) *recentCache {
	if maxAge <= 0 {
		panic("recent cache max age must be positive")
	}
	if maxSamples <= 0 {
		panic("recent cache max samples must be positive")
	}
	return &recentCache{
		maxAge:     maxAge,
		maxSamples: maxSamples,
		series:     make(map[cacheKey][]cachedSample),
	}
}

func (cache *recentCache) append(deviceName string, resourceName string, sample cachedSample) {
	key := cacheKey{deviceName: deviceName, resourceName: resourceName}

	cache.mu.Lock()
	defer cache.mu.Unlock()

	samples := cache.series[key]
	insertAt := sort.Search(len(samples), func(index int) bool {
		return samples[index].Origin > sample.Origin
	})
	samples = append(samples, cachedSample{})
	copy(samples[insertAt+1:], samples[insertAt:])
	samples[insertAt] = sample

	newestOrigin := samples[len(samples)-1].Origin
	cutoff := newestOrigin - cache.maxAge.Nanoseconds()
	firstRetained := sort.Search(len(samples), func(index int) bool {
		return samples[index].Origin >= cutoff
	})
	samples = samples[firstRetained:]
	if len(samples) > cache.maxSamples {
		samples = samples[len(samples)-cache.maxSamples:]
	}
	cache.series[key] = samples
}

func (cache *recentCache) latest(
	deviceName string,
	resourceName string,
	now int64,
) (cachedSample, bool) {
	samples := cache.query(
		deviceName,
		resourceName,
		now-cache.maxAge.Nanoseconds(),
		now,
		1,
		now,
	)
	if len(samples) == 0 {
		return cachedSample{}, false
	}
	return samples[0], true
}

func (cache *recentCache) query(
	deviceName string,
	resourceName string,
	from int64,
	to int64,
	limit int,
	now int64,
) []cachedSample {
	cache.mu.RLock()
	defer cache.mu.RUnlock()

	retentionStart := now - cache.maxAge.Nanoseconds()
	if from < retentionStart {
		from = retentionStart
	}
	if from > to || limit <= 0 {
		return []cachedSample{}
	}

	samples := cache.series[cacheKey{deviceName: deviceName, resourceName: resourceName}]
	start := sort.Search(len(samples), func(index int) bool {
		return samples[index].Origin >= from
	})
	end := sort.Search(len(samples), func(index int) bool {
		return samples[index].Origin > to
	})
	if start >= end {
		return []cachedSample{}
	}
	if end-start > limit {
		start = end - limit
	}

	result := make([]cachedSample, end-start)
	copy(result, samples[start:end])
	return result
}

func (cache *recentCache) deleteDevice(deviceName string) {
	cache.mu.Lock()
	defer cache.mu.Unlock()
	for key := range cache.series {
		if key.deviceName == deviceName {
			delete(cache.series, key)
		}
	}
}
