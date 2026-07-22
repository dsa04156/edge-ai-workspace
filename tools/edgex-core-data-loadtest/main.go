package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

const defaultCoreDataURL = "http://edgex-core-data.edgex-system.svc.cluster.local:59880"

func DefaultConfig() Config {
	return Config{
		BaseURL:                defaultCoreDataURL,
		RunID:                  generatedRunID(),
		Devices:                1000,
		PerDeviceHz:            1.0 / 60.0,
		Duration:               time.Minute,
		Concurrency:            128,
		MaintenanceConcurrency: 8,
		RequestTimeout:         5 * time.Second,
		MaxErrorRate:           0,
		MaxP95:                 time.Second,
		MinRateRatio:           0.95,
		Verify:                 true,
		Cleanup:                true,
	}
}

func generatedRunID() string {
	id, err := newUUID()
	if err != nil {
		return "run-" + time.Now().UTC().Format("20060102t150405000000000")
	}
	return fmt.Sprintf("run-%s-%s", time.Now().UTC().Format("20060102t150405"), strings.ReplaceAll(id, "-", "")[:8])
}

func ParseConfig(args []string, errorOutput io.Writer) (Config, error) {
	cfg := DefaultConfig()
	flags := flag.NewFlagSet("edgex-core-data-loadtest", flag.ContinueOnError)
	flags.SetOutput(errorOutput)
	flags.StringVar(&cfg.BaseURL, "base-url", cfg.BaseURL, "EdgeX Core Data base URL")
	flags.StringVar(&cfg.RunID, "run-id", cfg.RunID, "lowercase execution identifier")
	flags.IntVar(&cfg.Devices, "devices", cfg.Devices, "number of synthetic device identities")
	flags.Float64Var(&cfg.PerDeviceHz, "per-device-hz", cfg.PerDeviceHz, "events per second for each synthetic device")
	flags.DurationVar(&cfg.Duration, "duration", cfg.Duration, "load generation duration")
	flags.IntVar(&cfg.Concurrency, "concurrency", cfg.Concurrency, "maximum concurrent HTTP requests")
	flags.IntVar(&cfg.MaintenanceConcurrency, "maintenance-concurrency", cfg.MaintenanceConcurrency, "maximum concurrent readback and cleanup requests")
	flags.DurationVar(&cfg.RequestTimeout, "request-timeout", cfg.RequestTimeout, "per-request timeout")
	flags.Float64Var(&cfg.MaxErrorRate, "max-error-rate", cfg.MaxErrorRate, "maximum accepted failed request ratio")
	flags.DurationVar(&cfg.MaxP95, "max-p95", cfg.MaxP95, "maximum accepted p95 commit latency")
	flags.Float64Var(&cfg.MinRateRatio, "min-rate-ratio", cfg.MinRateRatio, "minimum achieved-to-target event rate ratio")
	flags.BoolVar(&cfg.Verify, "verify", cfg.Verify, "read back the dedicated Event count for every synthetic device")
	flags.BoolVar(&cfg.Cleanup, "cleanup", cfg.Cleanup, "delete events for every synthetic device after verification")
	if err := flags.Parse(args); err != nil {
		return Config{}, err
	}
	if flags.NArg() != 0 {
		return Config{}, fmt.Errorf("unexpected positional arguments: %s", strings.Join(flags.Args(), " "))
	}
	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	if PlannedEvents(cfg) <= 0 {
		return Config{}, fmt.Errorf("devices × per-device-hz × duration must plan at least one event")
	}
	return cfg, nil
}

func RunCLI(
	ctx context.Context,
	args []string,
	stdout io.Writer,
	stderr io.Writer,
	clientFactory func(Config) EventClient,
) int {
	cfg, err := ParseConfig(args, stderr)
	if err != nil {
		_, _ = fmt.Fprintf(stderr, "configuration error: %v\n", err)
		return 2
	}
	report := Run(ctx, cfg, clientFactory(cfg))
	encoder := json.NewEncoder(stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(report); err != nil {
		_, _ = fmt.Fprintf(stderr, "encode report: %v\n", err)
		return 2
	}
	if !report.Pass {
		return 1
	}
	return 0
}

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	os.Exit(RunCLI(ctx, os.Args[1:], os.Stdout, os.Stderr, func(cfg Config) EventClient {
		return NewHTTPClient(cfg)
	}))
}
