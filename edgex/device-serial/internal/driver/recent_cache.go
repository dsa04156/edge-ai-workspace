package driver

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"

	localcache "github.com/dsa04156/edge-ai-workspace/edgex/local-data-cache"
	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
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

type cachedSample = localcache.Sample[any]

type recentCacheConfig struct {
	maxAge     time.Duration
	maxSamples int
	maxBytes   int64
}

type recentCache struct {
	maxAge     time.Duration
	maxSamples int
	maxBytes   int64
	cache      *localcache.Cache[any]
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
	cache, err := localcache.New[any](localcache.Options{
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
	normalized, err := normalizeCachedSample(sample)
	if err != nil {
		return err
	}
	return cache.cache.Append(deviceName, resourceName, normalized)
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

func normalizeCachedSample(sample cachedSample) (cachedSample, error) {
	switch sample.ValueType {
	case common.ValueTypeInt32:
		value, err := cachedInt32(sample.Value)
		if err != nil {
			return cachedSample{}, err
		}
		sample.Value = value
	case common.ValueTypeFloat64:
		value, err := cachedFloat64(sample.Value)
		if err != nil {
			return cachedSample{}, err
		}
		sample.Value = value
	default:
		return cachedSample{}, fmt.Errorf(
			"unsupported cached value type %q",
			sample.ValueType,
		)
	}
	return sample, nil
}

func cachedInt32(value any) (int32, error) {
	switch typed := value.(type) {
	case int32:
		return typed, nil
	case int:
		if typed < math.MinInt32 || typed > math.MaxInt32 {
			break
		}
		return int32(typed), nil
	case int64:
		if typed < math.MinInt32 || typed > math.MaxInt32 {
			break
		}
		return int32(typed), nil
	case float64:
		if typed < math.MinInt32 || typed > math.MaxInt32 || typed != math.Trunc(typed) {
			break
		}
		return int32(typed), nil
	}
	return 0, fmt.Errorf("cached Int32 value has incompatible type %T", value)
}

func cachedFloat64(value any) (float64, error) {
	switch typed := value.(type) {
	case float64:
		if !math.IsNaN(typed) && !math.IsInf(typed, 0) {
			return typed, nil
		}
	case float32:
		value := float64(typed)
		if !math.IsNaN(value) && !math.IsInf(value, 0) {
			return value, nil
		}
	case int:
		return float64(typed), nil
	case int32:
		return float64(typed), nil
	case int64:
		return float64(typed), nil
	}
	return 0, fmt.Errorf("cached Float64 value has incompatible type %T", value)
}
