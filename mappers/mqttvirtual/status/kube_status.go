package status

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"time"

	"k8s.io/klog/v2"
)

const (
	serviceAccountTokenPath = "/var/run/secrets/kubernetes.io/serviceaccount/token"
	serviceAccountCAPath    = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
)

type deviceStatusResource struct {
	Status deviceStatusPatchStatus `json:"status"`
}

type deviceStatusPatch struct {
	Status deviceStatusPatchStatus `json:"status"`
}

type deviceStatusPatchStatus struct {
	ReportToCloud bool                    `json:"reportToCloud"`
	Twins         []deviceStatusPatchTwin `json:"twins"`
}

type deviceStatusPatchTwin struct {
	PropertyName string                         `json:"propertyName"`
	Reported     deviceStatusPatchPropertyValue `json:"reported"`
}

type deviceStatusPatchPropertyValue struct {
	Value    string            `json:"value"`
	Metadata map[string]string `json:"metadata,omitempty"`
}

func reportKubernetesDeviceStatus(ctx context.Context, summary Summary, values map[string]string) error {
	if !envBoolDefault("DEVICE_STATUS_K8S_PATCH_ENABLED", true) {
		return nil
	}
	apiServer := strings.TrimRight(strings.TrimSpace(os.Getenv("DEVICE_STATUS_K8S_API_SERVER")), "/")
	host := strings.TrimSpace(os.Getenv("KUBERNETES_SERVICE_HOST"))
	if host == "" && apiServer == "" {
		return nil
	}

	client, err := inClusterHTTPClient()
	if err != nil {
		return err
	}
	token, err := os.ReadFile(serviceAccountTokenPath)
	if err != nil {
		return fmt.Errorf("read Kubernetes service account token failed: %w", err)
	}

	endpoint := kubernetesDeviceStatusEndpoint(summary, apiServer)
	mergedValues, err := getCurrentKubernetesStatusValues(ctx, client, strings.TrimSpace(string(token)), endpoint)
	if err != nil {
		return err
	}
	for name, value := range values {
		if !IsSummaryField(name) {
			return fmt.Errorf("field %q is not allowed in Kubernetes Device status patch", name)
		}
		mergedValues[name] = value
	}

	payload, err := buildDeviceStatusStatusPatch(mergedValues)
	if err != nil {
		return err
	}
	if len(payload) == 0 {
		return nil
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPatch, endpoint, bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(token)))
	req.Header.Set("Content-Type", "application/merge-patch+json")
	req.Header.Set("Accept", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("patch Kubernetes Device status failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("patch Kubernetes Device status returned %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}
	klog.Infof("patched Kubernetes Device status deviceName=%s namespace=%s", summary.DeviceName, summary.DeviceNamespace)
	return nil
}

func getCurrentKubernetesStatusValues(ctx context.Context, client *http.Client, token, endpoint string) (map[string]string, error) {
	values := make(map[string]string)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("Accept", "application/json")

	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("get Kubernetes Device status failed: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return nil, fmt.Errorf("get Kubernetes Device status returned %s: %s", resp.Status, strings.TrimSpace(string(body)))
	}
	var resource deviceStatusResource
	if err := json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&resource); err != nil {
		return nil, fmt.Errorf("decode Kubernetes Device status failed: %w", err)
	}
	for _, twin := range resource.Status.Twins {
		if twin.PropertyName == "" || !IsSummaryField(twin.PropertyName) {
			continue
		}
		values[twin.PropertyName] = twin.Reported.Value
	}
	return values, nil
}

func kubernetesDeviceStatusEndpoint(summary Summary, apiServer string) string {
	namespace := strings.TrimSpace(summary.DeviceNamespace)
	if namespace == "" {
		namespace = "default"
	}
	path := fmt.Sprintf("/apis/devices.kubeedge.io/v1beta1/namespaces/%s/devices/%s/status",
		url.PathEscape(namespace),
		url.PathEscape(summary.DeviceName),
	)
	if apiServer != "" {
		return apiServer + path
	}
	port := strings.TrimSpace(os.Getenv("KUBERNETES_SERVICE_PORT_HTTPS"))
	if port == "" {
		port = strings.TrimSpace(os.Getenv("KUBERNETES_SERVICE_PORT"))
	}
	if port == "" {
		port = "443"
	}
	return fmt.Sprintf("https://%s:%s%s",
		strings.TrimSpace(os.Getenv("KUBERNETES_SERVICE_HOST")),
		port,
		path,
	)
}

func buildDeviceStatusStatusPatch(values map[string]string) ([]byte, error) {
	if len(values) == 0 {
		return nil, nil
	}
	names := make([]string, 0, len(values))
	for name := range values {
		if !IsSummaryField(name) {
			return nil, fmt.Errorf("field %q is not allowed in Kubernetes Device status patch", name)
		}
		names = append(names, name)
	}
	sort.Strings(names)

	now := time.Now().UTC().Format(time.RFC3339)
	patch := deviceStatusPatch{
		Status: deviceStatusPatchStatus{
			ReportToCloud: true,
			Twins:         make([]deviceStatusPatchTwin, 0, len(names)),
		},
	}
	for _, name := range names {
		patch.Status.Twins = append(patch.Status.Twins, deviceStatusPatchTwin{
			PropertyName: name,
			Reported: deviceStatusPatchPropertyValue{
				Value: values[name],
				Metadata: map[string]string{
					"type":      "string",
					"timestamp": now,
				},
			},
		})
	}
	return json.Marshal(patch)
}

func inClusterHTTPClient() (*http.Client, error) {
	ca, err := os.ReadFile(serviceAccountCAPath)
	if err != nil {
		return nil, fmt.Errorf("read Kubernetes service account CA failed: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(ca) {
		return nil, fmt.Errorf("append Kubernetes service account CA failed")
	}
	return &http.Client{
		Timeout: 10 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{RootCAs: pool, MinVersion: tls.VersionTLS12},
		},
	}, nil
}

func envBoolDefault(name string, fallback bool) bool {
	raw := strings.TrimSpace(strings.ToLower(os.Getenv(name)))
	if raw == "" {
		return fallback
	}
	switch raw {
	case "1", "true", "yes", "on":
		return true
	case "0", "false", "no", "off":
		return false
	default:
		return fallback
	}
}
