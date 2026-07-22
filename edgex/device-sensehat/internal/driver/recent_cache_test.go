package driver

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func floatSample(origin int64, value float64) cachedSample {
	return cachedSample{Origin: origin, ValueType: "Float64", Value: value}
}

func TestRecentCacheIsolatesSeriesAndReturnsNewestLimitInOrder(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10)
	base := time.Now().UnixNano()
	cache.append("device-a", "x", floatSample(base+3, 3))
	cache.append("device-a", "x", floatSample(base+1, 1))
	cache.append("device-a", "x", floatSample(base+2, 2))
	cache.append("device-b", "x", floatSample(base+4, 40))

	actual := cache.query("device-a", "x", base, base+10, 2, base+10)
	assert.Equal(t, []cachedSample{floatSample(base+2, 2), floatSample(base+3, 3)}, actual)
	latest, ok := cache.latest("device-b", "x", base+10)
	require.True(t, ok)
	assert.Equal(t, 40.0, latest.Value)
}

func TestRecentCacheAppliesAgeCapacityAndDelete(t *testing.T) {
	cache := newRecentCache(25*time.Nanosecond, 3)
	for index := int64(1); index <= 5; index++ {
		cache.append("device", "resource", floatSample(index*10, float64(index)))
	}
	assert.Equal(t, []cachedSample{
		floatSample(30, 3), floatSample(40, 4), floatSample(50, 5),
	}, cache.query("device", "resource", 0, 50, 10, 50))
	cache.deleteDevice("device")
	_, ok := cache.latest("device", "resource", 50)
	assert.False(t, ok)
}

func TestRecentCacheSupportsConcurrentReadWrite(t *testing.T) {
	cache := newRecentCache(time.Hour, 10_000)
	var group sync.WaitGroup
	for writer := 0; writer < 4; writer++ {
		writer := writer
		group.Add(1)
		go func() {
			defer group.Done()
			for index := 0; index < 250; index++ {
				origin := int64(writer*1000 + index + 1)
				cache.append("device", fmt.Sprintf("resource-%d", writer), floatSample(origin, float64(index)))
				_ = cache.query("device", fmt.Sprintf("resource-%d", writer), 0, origin, 10, origin)
			}
		}()
	}
	group.Wait()
	for writer := 0; writer < 4; writer++ {
		result := cache.query("device", fmt.Sprintf("resource-%d", writer), 0, 10_000, 300, 10_000)
		assert.Len(t, result, 250)
	}
}
