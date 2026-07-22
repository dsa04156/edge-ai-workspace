package driver

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	localcache "github.com/dsa04156/edge-ai-workspace/edgex/local-data-cache"
)

const (
	recentCacheMaxAge     = 10 * time.Minute
	recentCacheMaxSamples = 10_000
	recentCacheMaxBytes   = 64 * 1024 * 1024
	recentDefaultLimit    = 1_000
)

const (
	localDataCacheMaxAgeConfig     = "LocalDataCacheMaxAge"
	localDataCacheMaxSamplesConfig = "LocalDataCacheMaxSamplesPerSeries"
	localDataCacheMaxBytesConfig   = "LocalDataCacheMaxBytes"
)

type cachedSample = localcache.Sample[float64]

type recentCacheConfig struct {
	maxAge     time.Duration
	maxSamples int
	maxBytes   int64
}

type recentCache struct {
	maxAge     time.Duration
	maxSamples int
	maxBytes   int64
	cache      *localcache.Cache[float64]
}

func parseRecentCacheConfig(values map[string]string) (recentCacheConfig, error) {
	config := recentCacheConfig{
		maxAge:     recentCacheMaxAge,
		maxSamples: recentCacheMaxSamples,
		maxBytes:   recentCacheMaxBytes,
	}

	if raw, found := values[localDataCacheMaxAgeConfig]; found {
		value, err := time.ParseDuration(strings.TrimSpace(raw))
		if err != nil || value <= 0 {
			return recentCacheConfig{}, fmt.Errorf(
				"%s must be a positive duration",
				localDataCacheMaxAgeConfig,
			)
		}
		config.maxAge = value
	}
	if raw, found := values[localDataCacheMaxSamplesConfig]; found {
		value, err := strconv.Atoi(strings.TrimSpace(raw))
		if err != nil || value <= 0 {
			return recentCacheConfig{}, fmt.Errorf(
				"%s must be a positive base-10 integer",
				localDataCacheMaxSamplesConfig,
			)
		}
		config.maxSamples = value
	}
	if raw, found := values[localDataCacheMaxBytesConfig]; found {
		value, err := strconv.ParseInt(strings.TrimSpace(raw), 10, 64)
		if err != nil || value <= 0 {
			return recentCacheConfig{}, fmt.Errorf(
				"%s must be a positive base-10 integer",
				localDataCacheMaxBytesConfig,
			)
		}
		config.maxBytes = value
	}
	return config, nil
}

func newRecentCache(maxAge time.Duration, maxSamples int) *recentCache {
	cache, err := newConfiguredRecentCache(recentCacheConfig{
		maxAge:     maxAge,
		maxSamples: maxSamples,
		maxBytes:   recentCacheMaxBytes,
	}, nil)
	if err != nil {
		panic(err)
	}
	return cache
}

func newConfiguredRecentCache(
	config recentCacheConfig,
	observer localcache.Observer,
) (*recentCache, error) {
	cache, err := localcache.New[float64](localcache.Options{
		MaxAge:              config.maxAge,
		MaxSamplesPerSeries: config.maxSamples,
		MaxBytes:            config.maxBytes,
		Observer:            observer,
	})
	if err != nil {
		return nil, fmt.Errorf("create local data cache: %w", err)
	}
	return &recentCache{
		maxAge:     config.maxAge,
		maxSamples: config.maxSamples,
		maxBytes:   config.maxBytes,
		cache:      cache,
	}, nil
}

func (cache *recentCache) append(deviceName string, resourceName string, sample cachedSample) {
	if err := cache.appendChecked(deviceName, resourceName, sample); err != nil {
		panic(err)
	}
}

func (cache *recentCache) appendChecked(
	deviceName string,
	resourceName string,
	sample cachedSample,
) error {
	return cache.cache.Append(deviceName, resourceName, sample)
}

func (cache *recentCache) latest(
	deviceName string,
	resourceName string,
	now int64,
) (cachedSample, bool) {
	return cache.cache.Latest(deviceName, resourceName, now)
}

func (cache *recentCache) query(
	deviceName string,
	resourceName string,
	from int64,
	to int64,
	limit int,
	now int64,
) []cachedSample {
	return cache.cache.Query(deviceName, resourceName, from, to, limit, now)
}

func (cache *recentCache) deleteDevice(deviceName string) {
	cache.cache.DeleteDevice(deviceName)
}

func (cache *recentCache) stats() localcache.Stats {
	return cache.cache.Stats()
}
