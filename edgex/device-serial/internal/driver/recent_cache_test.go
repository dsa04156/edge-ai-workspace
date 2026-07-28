package driver

import (
	"sync"
	"testing"
	"time"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestRecentCacheSeparatesSourcesAndReturnsLatest(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10_000)
	now := int64(20 * time.Minute)
	cache.append("virtual-temperature-001", "temperature_raw", cachedSample{
		Origin:    now - int64(time.Second),
		ValueType: common.ValueTypeInt32,
		Value:     283,
	})
	cache.append("virtual-light-001", "light_raw", cachedSample{
		Origin:    now,
		ValueType: common.ValueTypeInt32,
		Value:     700,
	})

	latest, ok := cache.latest("virtual-temperature-001", "temperature_raw", now)
	require.True(t, ok)
	assert.Equal(t, int32(283), latest.Value)
	assert.Empty(t, cache.query(
		"virtual-temperature-001",
		"light_raw",
		now-int64(10*time.Minute),
		now,
		1_000,
		now,
	))
}

func TestRecentCacheEvictsByAgeAndCapacity(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 3)
	now := int64(20 * time.Minute)
	origins := []int64{
		now - int64(10*time.Minute) - 1,
		now - 3,
		now - 2,
		now - 1,
		now,
	}
	for index, origin := range origins {
		cache.append("device", "resource", cachedSample{
			Origin:    origin,
			ValueType: common.ValueTypeInt32,
			Value:     int32(index),
		})
	}

	got := cache.query("device", "resource", now-int64(10*time.Minute), now, 10, now)
	require.Len(t, got, 3)
	assert.Equal(t, []int64{now - 2, now - 1, now}, sampleOrigins(got))
}

func TestRecentCacheReturnsNewestLimitInAscendingOrder(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10)
	now := int64(20 * time.Minute)
	for value := int32(1); value <= 5; value++ {
		cache.append("device", "resource", cachedSample{
			Origin:    now - int64(6-value),
			ValueType: common.ValueTypeInt32,
			Value:     value,
		})
	}

	got := cache.query("device", "resource", now-10, now, 2, now)
	require.Len(t, got, 2)
	assert.Equal(t, []int32{4, 5}, []int32{
		got[0].Value.(int32),
		got[1].Value.(int32),
	})
	assert.Less(t, got[0].Origin, got[1].Origin)
}

func TestRecentCacheFiltersInclusiveOriginWindow(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10)
	now := int64(20 * time.Minute)
	for offset := int64(1); offset <= 5; offset++ {
		cache.append("device", "resource", cachedSample{
			Origin:    now - offset,
			ValueType: common.ValueTypeInt32,
			Value:     int32(offset),
		})
	}

	got := cache.query("device", "resource", now-4, now-2, 10, now)
	assert.Equal(t, []int64{now - 4, now - 3, now - 2}, sampleOrigins(got))
}

func TestRecentCacheExpiresLatestAndDeletesOnlyTargetDevice(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10)
	now := int64(20 * time.Minute)
	cache.append("expired", "resource", cachedSample{
		Origin:    now - int64(10*time.Minute) - 1,
		ValueType: common.ValueTypeInt32,
		Value:     1,
	})
	cache.append("remove", "resource", cachedSample{
		Origin:    now,
		ValueType: common.ValueTypeInt32,
		Value:     2,
	})
	cache.append("keep", "resource", cachedSample{
		Origin:    now,
		ValueType: common.ValueTypeInt32,
		Value:     3,
	})

	_, ok := cache.latest("expired", "resource", now)
	assert.False(t, ok)
	cache.deleteDevice("remove")
	_, ok = cache.latest("remove", "resource", now)
	assert.False(t, ok)
	kept, ok := cache.latest("keep", "resource", now)
	require.True(t, ok)
	assert.Equal(t, int32(3), kept.Value)
}

func TestRecentCacheConcurrentReadWriteRemainsBoundedAndSorted(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 100)
	now := int64(20 * time.Minute)
	var waitGroup sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		waitGroup.Add(1)
		go func(offset int) {
			defer waitGroup.Done()
			for index := 0; index < 100; index++ {
				origin := now + int64(offset*100+index)
				cache.append("device", "resource", cachedSample{
					Origin:    origin,
					ValueType: common.ValueTypeInt32,
					Value:     int32(index),
				})
				_ = cache.query(
					"device",
					"resource",
					now-int64(time.Minute),
					origin,
					10,
					origin,
				)
			}
		}(worker)
	}
	waitGroup.Wait()

	got := cache.query("device", "resource", now-int64(time.Minute), now+1_000, 10_000, now+1_000)
	assert.LessOrEqual(t, len(got), 100)
	assert.IsNonDecreasing(t, sampleOrigins(got))
}

func TestParseRecentCacheConfigUsesDefaultsAndRejectsInvalidValues(t *testing.T) {
	config, err := parseRecentCacheConfig(nil)
	require.NoError(t, err)
	assert.Equal(t, recentCacheMaxAge, config.maxAge)
	assert.Equal(t, recentCacheMaxSamples, config.maxSamples)
	assert.Equal(t, int64(recentCacheMaxBytes), config.maxBytes)

	for _, test := range []struct {
		name   string
		config map[string]string
		field  string
	}{
		{
			name:   "invalid age",
			config: map[string]string{"LocalDataCacheMaxAge": "not-a-duration"},
			field:  "LocalDataCacheMaxAge",
		},
		{
			name:   "zero samples",
			config: map[string]string{"LocalDataCacheMaxSamplesPerSeries": "0"},
			field:  "LocalDataCacheMaxSamplesPerSeries",
		},
		{
			name:   "zero bytes",
			config: map[string]string{"LocalDataCacheMaxBytes": "0"},
			field:  "LocalDataCacheMaxBytes",
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			_, err := parseRecentCacheConfig(test.config)
			assert.ErrorContains(t, err, test.field)
		})
	}
}

func TestRecentCacheReportsBoundedSlotStats(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10)
	cache.append("device", "resource", cachedSample{
		Origin:    1,
		ValueType: common.ValueTypeInt32,
		Value:     42,
	})

	stats := cache.stats()
	assert.Equal(t, 1, stats.Series)
	assert.Equal(t, 1, stats.Samples)
	assert.Equal(t, int64(recentCacheMaxBytes), stats.MaxBytes)
	assert.Positive(t, stats.SlotBytes)
	assert.LessOrEqual(t, stats.AllocatedBytes, stats.MaxBytes)
}

func sampleOrigins(samples []cachedSample) []int64 {
	origins := make([]int64, len(samples))
	for index, sample := range samples {
		origins[index] = sample.Origin
	}
	return origins
}
