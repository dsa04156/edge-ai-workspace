package driver

import (
	"bytes"
	"context"
	"errors"
	"io"
	"sync"
	"testing"
	"time"

	"github.com/edgexfoundry/go-mod-core-contracts/v4/models"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

type fakeProcess struct {
	stdout  io.Reader
	stderr  io.Reader
	waitErr error
	mu      sync.Mutex
	stopped bool
}

func (process *fakeProcess) Stdout() io.Reader { return process.stdout }
func (process *fakeProcess) Stderr() io.Reader { return process.stderr }
func (process *fakeProcess) Wait() error       { return process.waitErr }
func (process *fakeProcess) Stop() error {
	process.mu.Lock()
	defer process.mu.Unlock()
	process.stopped = true
	return nil
}
func (process *fakeProcess) wasStopped() bool {
	process.mu.Lock()
	defer process.mu.Unlock()
	return process.stopped
}

func TestSourceEmitsValidSamplesAndStateTransitions(t *testing.T) {
	process := &fakeProcess{
		stdout:  bytes.NewBufferString("not-json\n" + validSampleLine + "\n"),
		stderr:  bytes.NewBufferString("sensor diagnostic\n"),
		waitErr: errors.New("reader exited"),
	}
	samples := make(chan Sample, 1)
	states := make(chan models.OperatingState, 2)
	invalid := make(chan error, 1)
	diagnostics := make(chan string, 2)

	source := NewSource(I2CConfig{Bus: "/dev/i2c-1", DeviceID: "sensehat-001"}, SourceOptions{
		Start:         func(context.Context, I2CConfig) (Process, error) { return process, nil },
		Wait:          func(context.Context, time.Duration) bool { return false },
		OnSample:      func(sample Sample) { samples <- sample },
		OnState:       func(state models.OperatingState) { states <- state },
		OnInvalidLine: func(err error) { invalid <- err },
		OnDiagnostic:  func(line string) { diagnostics <- line },
	})

	source.Run(context.Background())

	assert.Error(t, <-invalid)
	assert.Equal(t, int64(123456789), (<-samples).Origin)
	assert.Equal(t, models.OperatingState(models.Up), <-states)
	assert.Equal(t, models.OperatingState(models.Down), <-states)
	assert.Equal(t, "sensor diagnostic", <-diagnostics)
}

func TestSourceCloseStopsActiveProcess(t *testing.T) {
	reader, writer := io.Pipe()
	process := &fakeProcess{stdout: reader, stderr: bytes.NewReader(nil)}
	started := make(chan struct{})
	source := NewSource(I2CConfig{Bus: "/dev/i2c-1", DeviceID: "sensehat-001"}, SourceOptions{
		Start: func(context.Context, I2CConfig) (Process, error) {
			close(started)
			return process, nil
		},
	})
	done := make(chan struct{})
	go func() {
		source.Run(context.Background())
		close(done)
	}()
	<-started

	require.NoError(t, source.Close())
	require.NoError(t, writer.Close())
	require.Eventually(t, process.wasStopped, time.Second, 5*time.Millisecond)
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)
}
