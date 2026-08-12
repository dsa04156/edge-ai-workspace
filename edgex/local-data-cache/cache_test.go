package localcache

import (
	"fmt"
	"sync"
	"testing"
	"time"
	"unsafe"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func intSample(origin int64, value int32) Sample[int32] {
	return Sample[int32]{Origin: origin, ValueType: "Int32", Value: value}
}

func sampleOrigins[T any](samples []Sample[T]) []int64 {
	origins := make([]int64, len(samples))
	for index, sample := range samples {
		origins[index] = sample.Origin
	}
	return origins
}

func TestNewValidatesOptions(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	tests := []struct {
		name    string
		options Options
		message string
	}{
		{name: "age", options: Options{MaxSamplesPerSeries: 1, MaxBytes: slotBytes}, message: "MaxAge"},
		{name: "samples", options: Options{MaxAge: time.Second, MaxBytes: slotBytes}, message: "MaxSamplesPerSeries"},
		{name: "bytes", options: Options{MaxAge: time.Second, MaxSamplesPerSeries: 1}, message: "MaxBytes"},
		{
			name:    "less than one slot",
			options: Options{MaxAge: time.Second, MaxSamplesPerSeries: 1, MaxBytes: slotBytes - 1},
			message: "sample slot",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := New[int32](test.options)
			assert.ErrorContains(t, err, test.message)
		})
	}
}

func TestCacheOverwritesOldestAtSeriesLimit(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 3, MaxBytes: slotBytes * 30,
	})
	require.NoError(t, err)

	for origin := int64(1); origin <= 5; origin++ {
		require.NoError(t, cache.Append("device", "resource", intSample(origin, int32(origin))))
	}

	actual := cache.Query("device", "resource", 0, 10, 10, 10)
	assert.Equal(t, []int64{3, 4, 5}, sampleOrigins(actual))
	assert.Equal(t, int64(2), cache.Stats().Evictions.SeriesLimit)
	latest, found := cache.Latest("device", "resource", 5)
	require.True(t, found)
	assert.Equal(t, int32(5), latest.Value)
}

func TestCacheEvictsByAgeAndClampsQueryToNow(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: 10 * time.Nanosecond, MaxSamplesPerSeries: 10, MaxBytes: slotBytes * 10,
	})
	require.NoError(t, err)

	for _, origin := range []int64{1, 10, 11, 20} {
		require.NoError(t, cache.Append("device", "resource", intSample(origin, int32(origin))))
	}

	assert.Equal(t, []int64{10, 11, 20}, sampleOrigins(
		cache.Query("device", "resource", 0, 20, 10, 20),
	))
	assert.Equal(t, int64(1), cache.Stats().Evictions.Age)
	_, found := cache.Latest("device", "resource", 31)
	assert.False(t, found)
}

func TestCacheRebalancesSeriesWithinByteBudget(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 4, MaxBytes: slotBytes * 4,
	})
	require.NoError(t, err)

	for _, resource := range []string{"a", "b"} {
		for origin := int64(1); origin <= 4; origin++ {
			require.NoError(t, cache.Append("device", resource, intSample(origin, int32(origin))))
		}
	}

	assert.Equal(t, []int64{3, 4}, sampleOrigins(cache.Query("device", "a", 0, 10, 10, 10)))
	assert.Equal(t, []int64{3, 4}, sampleOrigins(cache.Query("device", "b", 0, 10, 10, 10)))
	stats := cache.Stats()
	assert.Equal(t, 2, stats.Series)
	assert.Equal(t, 4, stats.Samples)
	assert.LessOrEqual(t, stats.AllocatedBytes, slotBytes*4)
	assert.Equal(t, slotBytes*4, stats.MaxBytes)
	assert.Equal(t, int64(2), stats.Evictions.GlobalRebalance)
	assert.Equal(t, int64(2), stats.Evictions.SeriesLimit)
}

func TestCacheRejectsMoreSeriesThanSlotBudget(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 10, MaxBytes: slotBytes,
	})
	require.NoError(t, err)
	require.NoError(t, cache.Append("device", "a", intSample(1, 1)))

	err = cache.Append("device", "b", intSample(2, 2))
	assert.ErrorContains(t, err, "active series")
	assert.Equal(t, 1, cache.Stats().Series)
	assert.Equal(t, []int64{1}, sampleOrigins(cache.Query("device", "a", 0, 10, 10, 10)))
}

func TestCacheKeepsOutOfOrderAndEqualOriginsStable(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 10, MaxBytes: slotBytes * 10,
	})
	require.NoError(t, err)

	for _, sample := range []Sample[int32]{
		intSample(3, 30), intSample(1, 10), intSample(2, 20), intSample(2, 21),
	} {
		require.NoError(t, cache.Append("device", "resource", sample))
	}

	actual := cache.Query("device", "resource", 0, 10, 10, 10)
	assert.Equal(t, []int64{1, 2, 2, 3}, sampleOrigins(actual))
	assert.Equal(t, []int32{10, 20, 21, 30}, []int32{
		actual[0].Value, actual[1].Value, actual[2].Value, actual[3].Value,
	})
	assert.Equal(t, []int32{21, 30}, []int32{
		cache.Query("device", "resource", 0, 10, 2, 10)[0].Value,
		cache.Query("device", "resource", 0, 10, 2, 10)[1].Value,
	})
}

func TestCacheDeleteDeviceUpdatesStatsAndObserver(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	observed := make([]Stats, 0)
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 10, MaxBytes: slotBytes * 20,
		Observer: func(stats Stats) { observed = append(observed, stats) },
	})
	require.NoError(t, err)
	require.NoError(t, cache.Append("remove", "a", intSample(1, 1)))
	require.NoError(t, cache.Append("keep", "b", intSample(2, 2)))

	cache.DeleteDevice("remove")
	stats := cache.Stats()
	assert.Equal(t, 1, stats.Series)
	assert.Equal(t, 1, stats.Samples)
	assert.NotEmpty(t, observed)
	assert.Equal(t, stats, observed[len(observed)-1])
}

func TestCacheConcurrentReadWriteRemainsBoundedAndSorted(t *testing.T) {
	slotBytes := int64(unsafe.Sizeof(Sample[int32]{}))
	cache, err := New[int32](Options{
		MaxAge: time.Hour, MaxSamplesPerSeries: 100, MaxBytes: slotBytes * 400,
	})
	require.NoError(t, err)

	var group sync.WaitGroup
	for writer := 0; writer < 4; writer++ {
		writer := writer
		group.Add(1)
		go func() {
			defer group.Done()
			resource := fmt.Sprintf("resource-%d", writer)
			for index := 0; index < 250; index++ {
				origin := int64(writer*1_000 + index + 1)
				require.NoError(t, cache.Append("device", resource, intSample(origin, int32(index))))
				_ = cache.Query("device", resource, 0, origin, 10, origin)
			}
		}()
	}
	group.Wait()

	for writer := 0; writer < 4; writer++ {
		actual := cache.Query("device", fmt.Sprintf("resource-%d", writer), 0, 10_000, 1_000, 10_000)
		assert.Len(t, actual, 100)
		assert.IsNonDecreasing(t, sampleOrigins(actual))
	}
	assert.LessOrEqual(t, cache.Stats().AllocatedBytes, slotBytes*400)
}
