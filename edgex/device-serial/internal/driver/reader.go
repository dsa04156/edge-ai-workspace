package driver

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"go.bug.st/serial"
)

const (
	defaultMaxLineBytes = 4096
	defaultReadTimeout  = time.Second
)

type Port interface {
	Read(buffer []byte) (int, error)
	SetReadTimeout(timeout time.Duration) error
	Close() error
}

type PortOpener func(path string, baudRate int) (Port, error)
type WaitFunc func(ctx context.Context, delay time.Duration) bool

type ReaderOptions struct {
	Open              PortOpener
	Wait              WaitFunc
	Now               func() int64
	RecoveryNow       func() time.Time
	OnSample          func(sample Sample, origin int64)
	OnState           func(state models.OperatingState)
	OnInvalidLine     func(err error)
	OnRecoveryStarted func(detectedAt time.Time)
	OnRecovery        func(observation RecoveryObservation)
	ReconnectDelays   []time.Duration
	MaxLineBytes      int
	ReadTimeout       time.Duration
}

type Reader struct {
	config            SerialConfig
	open              PortOpener
	wait              WaitFunc
	now               func() int64
	recoveryNow       func() time.Time
	onSample          func(Sample, int64)
	onState           func(models.OperatingState)
	onInvalidLine     func(error)
	onRecoveryStarted func(time.Time)
	onRecovery        func(RecoveryObservation)
	reconnectDelays   []time.Duration
	maxLineBytes      int
	readTimeout       time.Duration

	hasTransmitted   bool
	recoveryActive   bool
	recoveryStarted  time.Time
	recoveryAttempts int

	mu       sync.Mutex
	active   Port
	closed   bool
	stateMu  sync.Mutex
	state    models.OperatingState
	hasState bool
}

func NewReader(config SerialConfig, options ReaderOptions) *Reader {
	if options.Open == nil {
		options.Open = OpenSerial
	}
	if options.Wait == nil {
		options.Wait = waitForContext
	}
	if options.Now == nil {
		options.Now = func() int64 { return time.Now().UnixNano() }
	}
	if options.RecoveryNow == nil {
		options.RecoveryNow = time.Now
	}
	if options.OnSample == nil {
		options.OnSample = func(Sample, int64) {}
	}
	if options.OnState == nil {
		options.OnState = func(models.OperatingState) {}
	}
	if options.OnInvalidLine == nil {
		options.OnInvalidLine = func(error) {}
	}
	if options.OnRecoveryStarted == nil {
		options.OnRecoveryStarted = func(time.Time) {}
	}
	if options.OnRecovery == nil {
		options.OnRecovery = func(RecoveryObservation) {}
	}
	if len(options.ReconnectDelays) == 0 {
		options.ReconnectDelays = defaultSerialReconnectDelays
	}
	if options.MaxLineBytes <= 0 {
		options.MaxLineBytes = defaultMaxLineBytes
	}
	if options.ReadTimeout <= 0 {
		options.ReadTimeout = defaultReadTimeout
	}

	return &Reader{
		config:            config,
		open:              options.Open,
		wait:              options.Wait,
		now:               options.Now,
		recoveryNow:       options.RecoveryNow,
		onSample:          options.OnSample,
		onState:           options.OnState,
		onInvalidLine:     options.OnInvalidLine,
		onRecoveryStarted: options.OnRecoveryStarted,
		onRecovery:        options.OnRecovery,
		reconnectDelays:   append([]time.Duration(nil), options.ReconnectDelays...),
		maxLineBytes:      options.MaxLineBytes,
		readTimeout:       options.ReadTimeout,
	}
}

func OpenSerial(path string, baudRate int) (Port, error) {
	return serial.Open(path, &serial.Mode{
		BaudRate: baudRate,
		DataBits: 8,
		Parity:   serial.NoParity,
		StopBits: serial.OneStopBit,
	})
}

func (reader *Reader) Run(ctx context.Context) {
	failures := 0
	for {
		if reader.stopped(ctx) {
			return
		}

		reader.recordRecoveryAttempt()
		port, err := reader.open(reader.config.Port, reader.config.BaudRate)
		if err != nil {
			reader.beginRecovery()
			reader.emitState(models.OperatingState(models.Down))
			if !reader.wait(ctx, reconnectDelay(failures, reader.reconnectDelays)) {
				return
			}
			failures++
			continue
		}

		if !reader.activate(port) {
			_ = port.Close()
			return
		}
		if err := port.SetReadTimeout(reader.readTimeout); err != nil {
			reader.deactivate()
			if reader.stopped(ctx) {
				return
			}
			reader.beginRecovery()
			reader.emitState(models.OperatingState(models.Down))
			if !reader.wait(ctx, reconnectDelay(failures, reader.reconnectDelays)) {
				return
			}
			failures++
			continue
		}

		reader.emitState(models.OperatingState(models.Up))
		receivedBytes, readErr := reader.read(ctx, port)
		reader.deactivate()
		if reader.stopped(ctx) {
			return
		}
		if readErr == nil {
			return
		}

		reader.beginRecovery()
		reader.emitState(models.OperatingState(models.Down))
		if receivedBytes {
			failures = 0
		}
		if !reader.wait(ctx, reconnectDelay(failures, reader.reconnectDelays)) {
			return
		}
		failures++
	}
}

func (reader *Reader) Close() error {
	reader.mu.Lock()
	reader.closed = true
	active := reader.active
	reader.active = nil
	reader.mu.Unlock()
	if active == nil {
		return nil
	}
	return active.Close()
}

func (reader *Reader) read(ctx context.Context, port Port) (bool, error) {
	buffer := make([]byte, 1024)
	framer := NewLineFramer(reader.maxLineBytes)
	receivedBytes := false
	for {
		if reader.stopped(ctx) {
			return receivedBytes, nil
		}

		count, err := port.Read(buffer)
		if count > 0 {
			receivedBytes = true
			for _, line := range framer.Push(buffer[:count]) {
				sample, parseErr := ParseLineWithParser(
					line,
					reader.config.DeviceID,
					reader.config.Parser,
				)
				if parseErr != nil {
					reader.onInvalidLine(parseErr)
					continue
				}
				reader.emitSample(sample)
			}
		}
		if err != nil {
			return receivedBytes, err
		}
	}
}

func (reader *Reader) beginRecovery() {
	if !reader.hasTransmitted || reader.recoveryActive {
		return
	}
	reader.recoveryActive = true
	reader.recoveryStarted = reader.recoveryNow()
	reader.recoveryAttempts = 0
	reader.onRecoveryStarted(reader.recoveryStarted)
}

func (reader *Reader) recordRecoveryAttempt() {
	if reader.recoveryActive {
		reader.recoveryAttempts++
	}
}

func (reader *Reader) emitSample(sample Sample) {
	origin := reader.now()
	reader.onSample(sample, origin)
	reader.hasTransmitted = true
	if !reader.recoveryActive {
		return
	}

	resumedAt := reader.recoveryNow()
	observation := RecoveryObservation{
		DetectedAt: reader.recoveryStarted,
		ResumedAt:  resumedAt,
		Duration:   resumedAt.Sub(reader.recoveryStarted),
		Attempts:   reader.recoveryAttempts,
	}
	reader.recoveryActive = false
	reader.recoveryStarted = time.Time{}
	reader.recoveryAttempts = 0
	reader.onRecovery(observation)
}

func (reader *Reader) activate(port Port) bool {
	reader.mu.Lock()
	defer reader.mu.Unlock()
	if reader.closed {
		return false
	}
	reader.active = port
	return true
}

func (reader *Reader) deactivate() {
	reader.mu.Lock()
	active := reader.active
	reader.active = nil
	reader.mu.Unlock()
	if active != nil {
		_ = active.Close()
	}
}

func (reader *Reader) stopped(ctx context.Context) bool {
	if errors.Is(ctx.Err(), context.Canceled) || errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return true
	}
	reader.mu.Lock()
	defer reader.mu.Unlock()
	return reader.closed
}

func (reader *Reader) emitState(state models.OperatingState) {
	reader.stateMu.Lock()
	if reader.hasState && reader.state == state {
		reader.stateMu.Unlock()
		return
	}
	reader.state = state
	reader.hasState = true
	reader.stateMu.Unlock()
	reader.onState(state)
}

func reconnectDelay(failures int, delays []time.Duration) time.Duration {
	if len(delays) == 0 {
		delays = defaultSerialReconnectDelays
	}
	if failures < 0 {
		return delays[0]
	}
	if failures >= len(delays) {
		return delays[len(delays)-1]
	}
	return delays[failures]
}

func waitForContext(ctx context.Context, delay time.Duration) bool {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-timer.C:
		return true
	case <-ctx.Done():
		return false
	}
}
