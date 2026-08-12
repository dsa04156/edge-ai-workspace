package driver

import (
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"time"

	"github.com/labstack/echo/v4"
)

const (
	recentRoute = "/api/v3/localdata/device/name/:device/resource/name/:resource"
	latestRoute = recentRoute + "/latest"
	statsRoute  = "/api/v3/localdata/stats"
)

type retentionInfo struct {
	MaxAge     string `json:"maxAge"`
	MaxSamples int    `json:"maxSamples"`
	MaxBytes   int64  `json:"maxBytes"`
}

type localDataResponse struct {
	APIVersion   string         `json:"apiVersion"`
	StatusCode   int            `json:"statusCode"`
	DeviceName   string         `json:"deviceName"`
	ResourceName string         `json:"resourceName"`
	Count        int            `json:"count"`
	Retention    retentionInfo  `json:"retention"`
	Samples      []cachedSample `json:"samples"`
}

type localDataErrorResponse struct {
	APIVersion string `json:"apiVersion"`
	StatusCode int    `json:"statusCode"`
	Message    string `json:"message"`
}

type localDataEvictions struct {
	Age             int64 `json:"age"`
	SeriesLimit     int64 `json:"seriesLimit"`
	GlobalRebalance int64 `json:"globalRebalance"`
	Total           int64 `json:"total"`
}

type localDataStatsResponse struct {
	APIVersion     string             `json:"apiVersion"`
	StatusCode     int                `json:"statusCode"`
	Retention      retentionInfo      `json:"retention"`
	SlotBytes      int64              `json:"slotBytes"`
	Series         int                `json:"series"`
	Samples        int                `json:"samples"`
	AllocatedBytes int64              `json:"allocatedBytes"`
	Evictions      localDataEvictions `json:"evictions"`
}

type localDataAPI struct {
	cache   *recentCache
	isKnown func(deviceName string, resourceName string) bool
	now     func() int64
}

func newLocalDataAPI(cache *recentCache, isKnown func(string, string) bool) *localDataAPI {
	return &localDataAPI{
		cache:   cache,
		isKnown: isKnown,
		now:     func() int64 { return time.Now().UnixNano() },
	}
}

func (api *localDataAPI) latest(context echo.Context) error {
	deviceName, resourceName, known := api.knownSource(context)
	if !known {
		return api.writeError(context, http.StatusNotFound, fmt.Sprintf("unknown local data source %s/%s", deviceName, resourceName))
	}
	sample, found := api.cache.latest(deviceName, resourceName, api.now())
	if !found {
		return api.writeError(context, http.StatusNotFound, fmt.Sprintf("latest sample is unavailable for %s/%s", deviceName, resourceName))
	}
	return context.JSON(http.StatusOK, api.response(deviceName, resourceName, []cachedSample{sample}))
}

func (api *localDataAPI) recent(context echo.Context) error {
	deviceName, resourceName, known := api.knownSource(context)
	if !known {
		return api.writeError(context, http.StatusNotFound, fmt.Sprintf("unknown local data source %s/%s", deviceName, resourceName))
	}
	now := api.now()
	query := context.QueryParams()
	from, err := parseInt64Query(query, "from", now-api.cache.maxAge.Nanoseconds())
	if err != nil {
		return api.writeError(context, http.StatusBadRequest, err.Error())
	}
	to, err := parseInt64Query(query, "to", now)
	if err != nil {
		return api.writeError(context, http.StatusBadRequest, err.Error())
	}
	limit, err := parseLimitQuery(query)
	if err != nil {
		return api.writeError(context, http.StatusBadRequest, err.Error())
	}
	if from > to {
		return api.writeError(context, http.StatusBadRequest, "from must be less than or equal to to")
	}
	samples := api.cache.query(deviceName, resourceName, from, to, limit, now)
	return context.JSON(http.StatusOK, api.response(deviceName, resourceName, samples))
}

func (api *localDataAPI) stats(context echo.Context) error {
	stats := api.cache.stats()
	return context.JSON(http.StatusOK, localDataStatsResponse{
		APIVersion: "v3",
		StatusCode: http.StatusOK,
		Retention: retentionInfo{
			MaxAge:     stats.MaxAge.String(),
			MaxSamples: stats.MaxSamplesPerSeries,
			MaxBytes:   stats.MaxBytes,
		},
		SlotBytes:      stats.SlotBytes,
		Series:         stats.Series,
		Samples:        stats.Samples,
		AllocatedBytes: stats.AllocatedBytes,
		Evictions: localDataEvictions{
			Age:             stats.Evictions.Age,
			SeriesLimit:     stats.Evictions.SeriesLimit,
			GlobalRebalance: stats.Evictions.GlobalRebalance,
			Total:           stats.Evictions.Total(),
		},
	})
}

func (api *localDataAPI) knownSource(context echo.Context) (string, string, bool) {
	deviceName := context.Param("device")
	resourceName := context.Param("resource")
	return deviceName, resourceName, api.isKnown(deviceName, resourceName)
}

func (api *localDataAPI) response(deviceName string, resourceName string, samples []cachedSample) localDataResponse {
	if samples == nil {
		samples = []cachedSample{}
	}
	return localDataResponse{
		APIVersion:   "v3",
		StatusCode:   http.StatusOK,
		DeviceName:   deviceName,
		ResourceName: resourceName,
		Count:        len(samples),
		Retention: retentionInfo{
			MaxAge:     api.cache.maxAge.String(),
			MaxSamples: api.cache.maxSamples,
			MaxBytes:   api.cache.maxBytes,
		},
		Samples: samples,
	}
}

func (api *localDataAPI) writeError(context echo.Context, statusCode int, message string) error {
	return context.JSON(statusCode, localDataErrorResponse{
		APIVersion: "v3",
		StatusCode: statusCode,
		Message:    message,
	})
}

func parseInt64Query(values url.Values, name string, defaultValue int64) (int64, error) {
	rawValues, exists := values[name]
	if !exists {
		return defaultValue, nil
	}
	if len(rawValues) != 1 || rawValues[0] == "" {
		return 0, fmt.Errorf("%s must be one base-10 integer", name)
	}
	value, err := strconv.ParseInt(rawValues[0], 10, 64)
	if err != nil {
		return 0, fmt.Errorf("%s must be one base-10 integer", name)
	}
	return value, nil
}

func parseLimitQuery(values url.Values) (int, error) {
	rawValues, exists := values["limit"]
	if !exists {
		return recentDefaultLimit, nil
	}
	if len(rawValues) != 1 || rawValues[0] == "" {
		return 0, errorsForLimit()
	}
	limit, err := strconv.Atoi(rawValues[0])
	if err != nil || limit < 1 || limit > recentCacheMaxSamples {
		return 0, errorsForLimit()
	}
	return limit, nil
}

func errorsForLimit() error {
	return fmt.Errorf("limit must be one base-10 integer from 1 through %d", recentCacheMaxSamples)
}
