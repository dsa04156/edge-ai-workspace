package driver

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/common"
	"github.com/labstack/echo/v4"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestLocalDataAPIReturnsLatestAndRecentSamples(t *testing.T) {
	cache := newRecentCache(recentCacheMaxAge, recentCacheMaxSamples)
	now := int64(20 * time.Minute)
	cache.append("virtual-temperature-001", "temperature_raw", cachedSample{
		Origin:    now - 2,
		ValueType: common.ValueTypeInt32,
		Value:     282,
	})
	cache.append("virtual-temperature-001", "temperature_raw", cachedSample{
		Origin:    now - 1,
		ValueType: common.ValueTypeInt32,
		Value:     283,
	})
	api := newLocalDataAPI(cache, func(deviceName string, resourceName string) bool {
		return deviceName == "virtual-temperature-001" && resourceName == "temperature_raw"
	})
	api.now = func() int64 { return now }

	latestRecorder := executeLocalDataRequest(
		t,
		api.latest,
		latestRoute,
		"virtual-temperature-001",
		"temperature_raw",
	)
	assert.Equal(t, http.StatusOK, latestRecorder.Code)
	latest := decodeLocalDataResponse(t, latestRecorder)
	assert.Equal(t, "v3", latest.APIVersion)
	assert.Equal(t, http.StatusOK, latest.StatusCode)
	assert.Equal(t, "virtual-temperature-001", latest.DeviceName)
	assert.Equal(t, "temperature_raw", latest.ResourceName)
	assert.Equal(t, 1, latest.Count)
	require.Len(t, latest.Samples, 1)
	assert.Equal(t, common.ValueTypeInt32, latest.Samples[0].ValueType)
	assert.Equal(t, float64(283), latest.Samples[0].Value)
	assert.Equal(t, "10m0s", latest.Retention.MaxAge)
	assert.Equal(t, 10_000, latest.Retention.MaxSamples)
	assert.Equal(t, int64(recentCacheMaxBytes), latest.Retention.MaxBytes)

	recentRecorder := executeLocalDataRequest(
		t,
		api.recent,
		fmt.Sprintf("%s?from=%d&to=%d&limit=10", recentRoute, now-2, now-1),
		"virtual-temperature-001",
		"temperature_raw",
	)
	assert.Equal(t, http.StatusOK, recentRecorder.Code)
	recent := decodeLocalDataResponse(t, recentRecorder)
	assert.Equal(t, 2, recent.Count)
	require.Len(t, recent.Samples, 2)
	assert.Equal(t, []int64{now - 2, now - 1}, sampleOrigins(recent.Samples))
}

func TestLocalDataAPIReturnsFloat64Samples(t *testing.T) {
	cache := newRecentCache(recentCacheMaxAge, recentCacheMaxSamples)
	now := int64(20 * time.Minute)
	cache.append("mpu6050-imu-001", "acceleration_z", cachedSample{
		Origin:    now,
		ValueType: common.ValueTypeFloat64,
		Value:     9.80665,
	})
	api := newLocalDataAPI(cache, func(deviceName string, resourceName string) bool {
		return deviceName == "mpu6050-imu-001" && resourceName == "acceleration_z"
	})
	api.now = func() int64 { return now }

	recorder := executeLocalDataRequest(
		t,
		api.latest,
		latestRoute,
		"mpu6050-imu-001",
		"acceleration_z",
	)

	assert.Equal(t, http.StatusOK, recorder.Code)
	response := decodeLocalDataResponse(t, recorder)
	require.Len(t, response.Samples, 1)
	assert.Equal(t, common.ValueTypeFloat64, response.Samples[0].ValueType)
	assert.InDelta(t, 9.80665, response.Samples[0].Value, 0.000001)
}

func TestLocalDataAPIStatsReportsAllocationAndEvictions(t *testing.T) {
	cache := newRecentCache(recentCacheMaxAge, 1)
	cache.append("device", "resource", cachedSample{
		Origin:    1,
		ValueType: common.ValueTypeInt32,
		Value:     1,
	})
	cache.append("device", "resource", cachedSample{
		Origin:    2,
		ValueType: common.ValueTypeInt32,
		Value:     2,
	})
	api := newLocalDataAPI(cache, func(deviceName string, resourceName string) bool { return true })

	recorder := executeLocalDataRequest(t, api.stats, statsRoute, "", "")
	assert.Equal(t, http.StatusOK, recorder.Code)
	response := decodeLocalDataStatsResponse(t, recorder)
	assert.Equal(t, "v3", response.APIVersion)
	assert.Equal(t, http.StatusOK, response.StatusCode)
	assert.Equal(t, "10m0s", response.Retention.MaxAge)
	assert.Equal(t, 1, response.Retention.MaxSamples)
	assert.Equal(t, int64(recentCacheMaxBytes), response.Retention.MaxBytes)
	assert.Equal(t, 1, response.Series)
	assert.Equal(t, 1, response.Samples)
	assert.Positive(t, response.SlotBytes)
	assert.LessOrEqual(t, response.AllocatedBytes, response.Retention.MaxBytes)
	assert.Equal(t, int64(1), response.Evictions.SeriesLimit)
	assert.Equal(t, response.Evictions.Total, response.Evictions.SeriesLimit)
}

func TestLocalDataAPIRecentReturnsEmptyArrayForKnownSource(t *testing.T) {
	api := newLocalDataAPI(
		newRecentCache(recentCacheMaxAge, recentCacheMaxSamples),
		func(deviceName string, resourceName string) bool { return true },
	)
	api.now = func() int64 { return int64(20 * time.Minute) }

	recorder := executeLocalDataRequest(
		t,
		api.recent,
		recentRoute,
		"virtual-temperature-001",
		"temperature_raw",
	)
	assert.Equal(t, http.StatusOK, recorder.Code)
	response := decodeLocalDataResponse(t, recorder)
	assert.Equal(t, 0, response.Count)
	assert.NotNil(t, response.Samples)
	assert.Empty(t, response.Samples)
}

func TestLocalDataAPIReturnsNotFoundForUnknownSource(t *testing.T) {
	api := newLocalDataAPI(
		newRecentCache(recentCacheMaxAge, recentCacheMaxSamples),
		func(deviceName string, resourceName string) bool { return false },
	)

	for _, test := range []struct {
		name    string
		handler echo.HandlerFunc
		target  string
	}{
		{name: "latest", handler: api.latest, target: latestRoute},
		{name: "recent", handler: api.recent, target: recentRoute},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder := executeLocalDataRequest(
				t,
				test.handler,
				test.target,
				"unknown-device",
				"unknown-resource",
			)
			assert.Equal(t, http.StatusNotFound, recorder.Code)
			response := decodeLocalDataErrorResponse(t, recorder)
			assert.Equal(t, "v3", response.APIVersion)
			assert.Equal(t, http.StatusNotFound, response.StatusCode)
			assert.Contains(t, response.Message, "unknown local data source")
		})
	}
}

func TestLocalDataAPILatestReturnsNotFoundBeforeFirstOrAfterExpiredSample(t *testing.T) {
	cache := newRecentCache(recentCacheMaxAge, recentCacheMaxSamples)
	now := int64(20 * time.Minute)
	api := newLocalDataAPI(cache, func(deviceName string, resourceName string) bool { return true })
	api.now = func() int64 { return now }

	for _, name := range []string{"before first sample", "after expired sample"} {
		t.Run(name, func(t *testing.T) {
			if name == "after expired sample" {
				cache.append("device", "resource", cachedSample{
					Origin:    now - int64(recentCacheMaxAge) - 1,
					ValueType: common.ValueTypeInt32,
					Value:     1,
				})
			}
			recorder := executeLocalDataRequest(t, api.latest, latestRoute, "device", "resource")
			assert.Equal(t, http.StatusNotFound, recorder.Code)
			assert.Contains(t, decodeLocalDataErrorResponse(t, recorder).Message, "latest sample is unavailable")
		})
	}
}

func TestLocalDataAPIRecentDefaultsToNewestThousandSamples(t *testing.T) {
	cache := newRecentCache(recentCacheMaxAge, recentCacheMaxSamples)
	now := int64(20 * time.Minute)
	for index := int64(0); index < 1_001; index++ {
		cache.append("device", "resource", cachedSample{
			Origin:    now - 1_000 + index,
			ValueType: common.ValueTypeInt32,
			Value:     int32(index),
		})
	}
	api := newLocalDataAPI(cache, func(deviceName string, resourceName string) bool { return true })
	api.now = func() int64 { return now }

	recorder := executeLocalDataRequest(t, api.recent, recentRoute, "device", "resource")
	assert.Equal(t, http.StatusOK, recorder.Code)
	response := decodeLocalDataResponse(t, recorder)
	require.Len(t, response.Samples, recentDefaultLimit)
	assert.Equal(t, float64(1), response.Samples[0].Value)
	assert.Equal(t, float64(1_000), response.Samples[len(response.Samples)-1].Value)
}

func TestLocalDataAPIRejectsInvalidRecentQuery(t *testing.T) {
	api := newLocalDataAPI(
		newRecentCache(recentCacheMaxAge, recentCacheMaxSamples),
		func(deviceName string, resourceName string) bool { return true },
	)
	api.now = func() int64 { return int64(20 * time.Minute) }

	for _, rawQuery := range []string{
		"from=nope",
		"to=nope",
		"from=2&to=1",
		"limit=nope",
		"limit=0",
		"limit=10001",
	} {
		t.Run(rawQuery, func(t *testing.T) {
			recorder := executeLocalDataRequest(
				t,
				api.recent,
				recentRoute+"?"+rawQuery,
				"virtual-temperature-001",
				"temperature_raw",
			)
			assert.Equal(t, http.StatusBadRequest, recorder.Code)
			response := decodeLocalDataErrorResponse(t, recorder)
			assert.Equal(t, http.StatusBadRequest, response.StatusCode)
			assert.NotEmpty(t, response.Message)
		})
	}
}

func executeLocalDataRequest(
	t *testing.T,
	handler echo.HandlerFunc,
	target string,
	deviceName string,
	resourceName string,
) *httptest.ResponseRecorder {
	t.Helper()
	request := httptest.NewRequest(http.MethodGet, target, http.NoBody)
	recorder := httptest.NewRecorder()
	context := echo.New().NewContext(request, recorder)
	context.SetParamNames("device", "resource")
	context.SetParamValues(deviceName, resourceName)
	require.NoError(t, handler(context))
	return recorder
}

func decodeLocalDataResponse(t *testing.T, recorder *httptest.ResponseRecorder) localDataResponse {
	t.Helper()
	var response localDataResponse
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	return response
}

func decodeLocalDataErrorResponse(t *testing.T, recorder *httptest.ResponseRecorder) localDataErrorResponse {
	t.Helper()
	var response localDataErrorResponse
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	return response
}

func decodeLocalDataStatsResponse(t *testing.T, recorder *httptest.ResponseRecorder) localDataStatsResponse {
	t.Helper()
	var response localDataStatsResponse
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
	return response
}
