package driver

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/labstack/echo/v4"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func localRequest(t *testing.T, api *localDataAPI, path string, latest bool) *httptest.ResponseRecorder {
	t.Helper()
	e := echo.New()
	request := httptest.NewRequest(http.MethodGet, path, nil)
	recorder := httptest.NewRecorder()
	context := e.NewContext(request, recorder)
	context.SetPath(recentRoute)
	context.SetParamNames("device", "resource")
	context.SetParamValues("env-sensehat-humidity-01", "humidity")
	var err error
	if latest {
		err = api.latest(context)
	} else {
		err = api.recent(context)
	}
	require.NoError(t, err)
	return recorder
}

func TestLocalDataAPIReturnsFloatLatestAndRecentSamples(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10_000)
	now := int64(1_000_000_000_000)
	cache.append("env-sensehat-humidity-01", "humidity", floatSample(now-2, 35.1))
	cache.append("env-sensehat-humidity-01", "humidity", floatSample(now-1, 35.2))
	api := newLocalDataAPI(cache, func(device, resource string) bool {
		return device == "env-sensehat-humidity-01" && resource == "humidity"
	})
	api.now = func() int64 { return now }

	latest := localRequest(t, api, "/api/v3/localdata/device/name/x/resource/name/y/latest", true)
	assert.Equal(t, http.StatusOK, latest.Code)
	var latestBody localDataResponse
	require.NoError(t, json.Unmarshal(latest.Body.Bytes(), &latestBody))
	assert.Equal(t, []cachedSample{floatSample(now-1, 35.2)}, latestBody.Samples)

	recent := localRequest(t, api, "/api/v3/localdata/device/name/x/resource/name/y?limit=1", false)
	assert.Equal(t, http.StatusOK, recent.Code)
	var recentBody localDataResponse
	require.NoError(t, json.Unmarshal(recent.Body.Bytes(), &recentBody))
	assert.Equal(t, 1, recentBody.Count)
	assert.Equal(t, 35.2, recentBody.Samples[0].Value)
	assert.Equal(t, "10m0s", recentBody.Retention.MaxAge)
	assert.Equal(t, 10_000, recentBody.Retention.MaxSamples)
	assert.Equal(t, int64(recentCacheMaxBytes), recentBody.Retention.MaxBytes)
}

func TestLocalDataAPIStatsReportsAllocationAndEvictions(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 1)
	cache.append("device", "humidity", floatSample(1, 35.1))
	cache.append("device", "humidity", floatSample(2, 35.2))
	api := newLocalDataAPI(cache, func(string, string) bool { return true })

	e := echo.New()
	request := httptest.NewRequest(http.MethodGet, statsRoute, nil)
	recorder := httptest.NewRecorder()
	require.NoError(t, api.stats(e.NewContext(request, recorder)))
	assert.Equal(t, http.StatusOK, recorder.Code)

	var response localDataStatsResponse
	require.NoError(t, json.Unmarshal(recorder.Body.Bytes(), &response))
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

func TestLocalDataAPIErrorAndEmptyContracts(t *testing.T) {
	cache := newRecentCache(10*time.Minute, 10_000)
	api := newLocalDataAPI(cache, func(device, resource string) bool {
		return device == "env-sensehat-humidity-01" && resource == "humidity"
	})
	api.now = func() int64 { return 1_000_000_000_000 }

	empty := localRequest(t, api, "/api/v3/localdata/device/name/x/resource/name/y?limit=20", false)
	assert.Equal(t, http.StatusOK, empty.Code)
	assert.JSONEq(t, `{"apiVersion":"v3","statusCode":200,"deviceName":"env-sensehat-humidity-01","resourceName":"humidity","count":0,"retention":{"maxAge":"10m0s","maxSamples":10000,"maxBytes":67108864},"samples":[]}`, empty.Body.String())

	invalid := localRequest(t, api, "/api/v3/localdata/device/name/x/resource/name/y?limit=10001", false)
	assert.Equal(t, http.StatusBadRequest, invalid.Code)

	unknownAPI := newLocalDataAPI(cache, func(string, string) bool { return false })
	unknown := localRequest(t, unknownAPI, "/api/v3/localdata/device/name/x/resource/name/y", false)
	assert.Equal(t, http.StatusNotFound, unknown.Code)

	missingLatest := localRequest(t, api, "/api/v3/localdata/device/name/x/resource/name/y/latest", true)
	assert.Equal(t, http.StatusNotFound, missingLatest.Code)
}
