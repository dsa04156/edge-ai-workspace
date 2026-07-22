package localcache

import (
	"fmt"
	"sync"
	"time"
	"unsafe"
)

// Sample is one typed device resource value stored in the local recent cache.
type Sample[T any] struct {
	Origin    int64  `json:"origin"`
	ValueType string `json:"valueType"`
	Value     T      `json:"value"`
}

// Observer receives an immutable cache statistics snapshot after each mutation.
type Observer func(Stats)

// Options defines the retention and allocation bounds for a Cache.
type Options struct {
	MaxAge              time.Duration
	MaxSamplesPerSeries int
	MaxBytes            int64
	Observer            Observer
}

// EvictionStats separates retention causes while preserving a total count.
type EvictionStats struct {
	Age             int64 `json:"age"`
	SeriesLimit     int64 `json:"seriesLimit"`
	GlobalRebalance int64 `json:"globalRebalance"`
}

// Total returns all cache evictions.
func (stats EvictionStats) Total() int64 {
	return stats.Age + stats.SeriesLimit + stats.GlobalRebalance
}

// Stats describes current logical contents and allocated sample ring slots.
type Stats struct {
	MaxAge              time.Duration `json:"-"`
	MaxSamplesPerSeries int           `json:"maxSamplesPerSeries"`
	MaxBytes            int64         `json:"maxBytes"`
	SlotBytes           int64         `json:"slotBytes"`
	Series              int           `json:"series"`
	Samples             int           `json:"samples"`
	AllocatedBytes      int64         `json:"allocatedBytes"`
	Evictions           EvictionStats `json:"evictions"`
}

type cacheKey struct {
	deviceName   string
	resourceName string
}

// Cache stores an independently bounded ring for every device/resource pair.
type Cache[T any] struct {
	mu                  sync.RWMutex
	maxAge              time.Duration
	maxSamplesPerSeries int
	maxBytes            int64
	slotBytes           int64
	totalSlotBudget     int
	series              map[cacheKey]*sampleRing[T]
	evictions           EvictionStats
	observer            Observer
}

// New validates the bounds and constructs an empty cache.
func New[T any](options Options) (*Cache[T], error) {
	if options.MaxAge <= 0 {
		return nil, fmt.Errorf("MaxAge must be positive")
	}
	if options.MaxSamplesPerSeries <= 0 {
		return nil, fmt.Errorf("MaxSamplesPerSeries must be positive")
	}
	if options.MaxBytes <= 0 {
		return nil, fmt.Errorf("MaxBytes must be positive")
	}

	slotBytes := int64(unsafe.Sizeof(Sample[T]{}))
	if options.MaxBytes < slotBytes {
		return nil, fmt.Errorf("MaxBytes must hold at least one sample slot (%d bytes)", slotBytes)
	}
	totalSlots := options.MaxBytes / slotBytes
	maxInt := int64(^uint(0) >> 1)
	if totalSlots > maxInt {
		totalSlots = maxInt
	}

	return &Cache[T]{
		maxAge:              options.MaxAge,
		maxSamplesPerSeries: options.MaxSamplesPerSeries,
		maxBytes:            options.MaxBytes,
		slotBytes:           slotBytes,
		totalSlotBudget:     int(totalSlots),
		series:              make(map[cacheKey]*sampleRing[T]),
		observer:            options.Observer,
	}, nil
}

// Append adds one sample. Monotonic origins use the ring's O(1) fast path.
func (cache *Cache[T]) Append(
	deviceName string,
	resourceName string,
	sample Sample[T],
) error {
	if deviceName == "" {
		return fmt.Errorf("device name must not be empty")
	}
	if resourceName == "" {
		return fmt.Errorf("resource name must not be empty")
	}

	key := cacheKey{deviceName: deviceName, resourceName: resourceName}
	cache.mu.Lock()
	series, found := cache.series[key]
	if !found {
		quota := cache.seriesQuota(len(cache.series) + 1)
		if quota < 1 {
			cache.mu.Unlock()
			return fmt.Errorf(
				"MaxBytes cannot allocate one sample slot to %d active series",
				len(cache.series)+1,
			)
		}
		for _, existing := range cache.series {
			cache.evictions.GlobalRebalance += int64(existing.setMaxCapacity(quota))
		}
		series = newSampleRing[T](quota)
		cache.series[key] = series
	}

	ageEvicted, limitEvicted := series.append(sample, cache.maxAge)
	cache.evictions.Age += int64(ageEvicted)
	cache.evictions.SeriesLimit += int64(limitEvicted)
	stats := cache.statsLocked()
	observer := cache.observer
	cache.mu.Unlock()

	if observer != nil {
		observer(stats)
	}
	return nil
}

// Latest returns the newest non-expired sample at now.
func (cache *Cache[T]) Latest(
	deviceName string,
	resourceName string,
	now int64,
) (Sample[T], bool) {
	samples := cache.Query(
		deviceName,
		resourceName,
		now-cache.maxAge.Nanoseconds(),
		now,
		1,
		now,
	)
	if len(samples) == 0 {
		return Sample[T]{}, false
	}
	return samples[0], true
}

// Query returns the newest limit samples in the inclusive origin window,
// ordered from oldest to newest.
func (cache *Cache[T]) Query(
	deviceName string,
	resourceName string,
	from int64,
	to int64,
	limit int,
	now int64,
) []Sample[T] {
	retentionStart := now - cache.maxAge.Nanoseconds()
	if from < retentionStart {
		from = retentionStart
	}
	if from > to || limit <= 0 {
		return []Sample[T]{}
	}

	cache.mu.RLock()
	series := cache.series[cacheKey{deviceName: deviceName, resourceName: resourceName}]
	if series == nil {
		cache.mu.RUnlock()
		return []Sample[T]{}
	}
	result := series.query(from, to, limit)
	cache.mu.RUnlock()
	return result
}

// DeleteDevice removes every resource series owned by deviceName.
func (cache *Cache[T]) DeleteDevice(deviceName string) {
	cache.mu.Lock()
	for key := range cache.series {
		if key.deviceName == deviceName {
			delete(cache.series, key)
		}
	}
	quota := cache.seriesQuota(len(cache.series))
	if quota > 0 {
		for _, series := range cache.series {
			series.setMaxCapacity(quota)
		}
	}
	stats := cache.statsLocked()
	observer := cache.observer
	cache.mu.Unlock()

	if observer != nil {
		observer(stats)
	}
}

// Stats returns a point-in-time statistics snapshot.
func (cache *Cache[T]) Stats() Stats {
	cache.mu.RLock()
	defer cache.mu.RUnlock()
	return cache.statsLocked()
}

func (cache *Cache[T]) seriesQuota(seriesCount int) int {
	if seriesCount == 0 {
		return cache.maxSamplesPerSeries
	}
	quota := cache.totalSlotBudget / seriesCount
	if quota > cache.maxSamplesPerSeries {
		return cache.maxSamplesPerSeries
	}
	return quota
}

func (cache *Cache[T]) statsLocked() Stats {
	stats := Stats{
		MaxAge:              cache.maxAge,
		MaxSamplesPerSeries: cache.maxSamplesPerSeries,
		MaxBytes:            cache.maxBytes,
		SlotBytes:           cache.slotBytes,
		Series:              len(cache.series),
		Evictions:           cache.evictions,
	}
	for _, series := range cache.series {
		stats.Samples += series.size
		stats.AllocatedBytes += int64(series.capacity()) * cache.slotBytes
	}
	return stats
}
