package driver

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
)

const (
	readerExecutable = "/usr/bin/python3"
	readerScript     = "/opt/device-sensehat/read_sensehat.py"
	maxSampleBytes   = 16 * 1024
)

type Process interface {
	Stdout() io.Reader
	Stderr() io.Reader
	Wait() error
	Stop() error
}

type StartProcess func(ctx context.Context, config I2CConfig) (Process, error)
type SourceWaitFunc func(ctx context.Context, delay time.Duration) bool

type SourceOptions struct {
	Start         StartProcess
	Wait          SourceWaitFunc
	OnSample      func(Sample)
	OnState       func(models.OperatingState)
	OnInvalidLine func(error)
	OnDiagnostic  func(string)
}

type Source struct {
	config        I2CConfig
	start         StartProcess
	wait          SourceWaitFunc
	onSample      func(Sample)
	onState       func(models.OperatingState)
	onInvalidLine func(error)
	onDiagnostic  func(string)

	mu       sync.Mutex
	active   Process
	closed   bool
	stateMu  sync.Mutex
	state    models.OperatingState
	hasState bool
}

func NewSource(config I2CConfig, options SourceOptions) *Source {
	if options.Start == nil {
		options.Start = startReaderProcess
	}
	if options.Wait == nil {
		options.Wait = waitForSourceContext
	}
	if options.OnSample == nil {
		options.OnSample = func(Sample) {}
	}
	if options.OnState == nil {
		options.OnState = func(models.OperatingState) {}
	}
	if options.OnInvalidLine == nil {
		options.OnInvalidLine = func(error) {}
	}
	if options.OnDiagnostic == nil {
		options.OnDiagnostic = func(string) {}
	}
	return &Source{
		config:        config,
		start:         options.Start,
		wait:          options.Wait,
		onSample:      options.OnSample,
		onState:       options.OnState,
		onInvalidLine: options.OnInvalidLine,
		onDiagnostic:  options.OnDiagnostic,
	}
}

func (source *Source) Run(ctx context.Context) {
	failures := 0
	for {
		if source.stopped(ctx) {
			return
		}
		process, err := source.start(ctx, source.config)
		if err != nil {
			source.emitState(models.OperatingState(models.Down))
			if !source.wait(ctx, sourceReconnectDelay(failures)) {
				return
			}
			failures++
			continue
		}
		if !source.activate(process) {
			_ = process.Stop()
			return
		}

		diagnosticDone := make(chan struct{})
		go func() {
			source.readDiagnostics(process.Stderr())
			close(diagnosticDone)
		}()
		received := source.readSamples(ctx, process.Stdout())
		waitErr := process.Wait()
		source.deactivate(process)
		<-diagnosticDone
		if source.stopped(ctx) {
			return
		}
		if waitErr != nil {
			source.onDiagnostic(waitErr.Error())
		}
		source.emitState(models.OperatingState(models.Down))
		if received {
			failures = 0
		}
		if !source.wait(ctx, sourceReconnectDelay(failures)) {
			return
		}
		failures++
	}
}

func (source *Source) Close() error {
	source.mu.Lock()
	source.closed = true
	active := source.active
	source.active = nil
	source.mu.Unlock()
	if active == nil {
		return nil
	}
	return active.Stop()
}

func (source *Source) readSamples(ctx context.Context, input io.Reader) bool {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 4096), maxSampleBytes)
	received := false
	for scanner.Scan() {
		if source.stopped(ctx) {
			return received
		}
		sample, err := ParseSample(scanner.Bytes(), source.config.DeviceID)
		if err != nil {
			source.onInvalidLine(err)
			continue
		}
		received = true
		source.onSample(sample)
		source.emitState(models.OperatingState(models.Up))
	}
	if err := scanner.Err(); err != nil && !source.stopped(ctx) {
		source.onInvalidLine(err)
	}
	return received
}

func (source *Source) readDiagnostics(input io.Reader) {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 1024), maxSampleBytes)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line != "" {
			source.onDiagnostic(line)
		}
	}
}

func (source *Source) activate(process Process) bool {
	source.mu.Lock()
	defer source.mu.Unlock()
	if source.closed {
		return false
	}
	source.active = process
	return true
}

func (source *Source) deactivate(process Process) {
	source.mu.Lock()
	if source.active == process {
		source.active = nil
	}
	source.mu.Unlock()
}

func (source *Source) stopped(ctx context.Context) bool {
	if errors.Is(ctx.Err(), context.Canceled) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return true
	}
	source.mu.Lock()
	defer source.mu.Unlock()
	return source.closed
}

func (source *Source) emitState(state models.OperatingState) {
	source.stateMu.Lock()
	if source.hasState && source.state == state {
		source.stateMu.Unlock()
		return
	}
	source.state = state
	source.hasState = true
	source.stateMu.Unlock()
	source.onState(state)
}

func sourceReconnectDelay(failures int) time.Duration {
	delays := [...]time.Duration{
		time.Second,
		2 * time.Second,
		4 * time.Second,
		8 * time.Second,
		16 * time.Second,
		30 * time.Second,
	}
	if failures < 0 {
		return delays[0]
	}
	if failures >= len(delays) {
		return delays[len(delays)-1]
	}
	return delays[failures]
}

func waitForSourceContext(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-ctx.Done():
		return false
	}
}

type commandProcess struct {
	command *exec.Cmd
	stdout  io.Reader
	stderr  io.Reader
}

func startReaderProcess(ctx context.Context, config I2CConfig) (Process, error) {
	command := exec.CommandContext(
		ctx,
		readerExecutable,
		readerScript,
		"--device-id",
		config.DeviceID,
		"--interval",
		"1",
	)
	stdout, err := command.StdoutPipe()
	if err != nil {
		return nil, err
	}
	stderr, err := command.StderrPipe()
	if err != nil {
		return nil, err
	}
	if err := command.Start(); err != nil {
		return nil, err
	}
	return &commandProcess{command: command, stdout: stdout, stderr: stderr}, nil
}

func (process *commandProcess) Stdout() io.Reader { return process.stdout }
func (process *commandProcess) Stderr() io.Reader { return process.stderr }
func (process *commandProcess) Wait() error       { return process.command.Wait() }
func (process *commandProcess) Stop() error {
	if process.command.Process == nil {
		return nil
	}
	err := process.command.Process.Kill()
	if errors.Is(err, os.ErrProcessDone) {
		return nil
	}
	return err
}
