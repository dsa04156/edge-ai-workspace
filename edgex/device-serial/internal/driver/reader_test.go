package driver

import (
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

func TestReconnectDelayIsBounded(t *testing.T) {
	assert.Equal(t, time.Second, reconnectDelay(0))
	assert.Equal(t, 2*time.Second, reconnectDelay(1))
	assert.Equal(t, 4*time.Second, reconnectDelay(2))
	assert.Equal(t, 8*time.Second, reconnectDelay(3))
	assert.Equal(t, 16*time.Second, reconnectDelay(4))
	assert.Equal(t, 30*time.Second, reconnectDelay(5))
	assert.Equal(t, 30*time.Second, reconnectDelay(100))
}

func TestReaderDropsInvalidLineAndEmitsFollowingSample(t *testing.T) {
	port := newScriptedPort(
		readResult{data: []byte(`_id":"arduino-001","sensor":"light","value":1}` + "\n")},
		readResult{data: []byte(`{"device_id":"arduino-001","sensor":"light","value":400}` + "\n")},
	)
	samples := make(chan Sample, 1)
	invalid := make(chan error, 1)
	states := make(chan models.OperatingState, 2)
	reader := NewReader(testSerialConfig(), ReaderOptions{
		Open: func(string, int) (Port, error) { return port, nil },
		Now:  func() int64 { return 123456789 },
		OnSample: func(sample Sample, origin int64) {
			assert.Equal(t, int64(123456789), origin)
			samples <- sample
		},
		OnInvalidLine: func(err error) { invalid <- err },
		OnState:       func(state models.OperatingState) { states <- state },
	})

	done := make(chan struct{})
	go func() {
		reader.Run(context.Background())
		close(done)
	}()

	require.Eventually(t, func() bool { return len(samples) == 1 }, time.Second, 5*time.Millisecond)
	require.NoError(t, reader.Close())
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)

	assert.Error(t, <-invalid)
	assert.Equal(t, models.OperatingState(models.Up), <-states)
	assert.Equal(t, Sample{
		DeviceName: "arduino-001",
		SourceName: "light",
		Readings:   []Reading{{ResourceName: "light_raw", Value: 400}},
	}, <-samples)
	assert.Equal(t, time.Second, port.readTimeout())
}

func TestReaderUsesConfiguredMPU6050Parser(t *testing.T) {
	port := newScriptedPort(readResult{data: []byte(
		`{"device_id":"mpu6050-001","sensor":"imu",` +
			`"acceleration_x":0.1,"acceleration_y":0.2,` +
			`"acceleration_z":9.8,"gyro_x":0.01,` +
			`"gyro_y":0.02,"gyro_z":0.03}` + "\n",
	)})
	samples := make(chan Sample, 1)
	reader := NewReader(SerialConfig{
		Port:     "/dev/mpu6050-001",
		BaudRate: 115200,
		DeviceID: "mpu6050-001",
		Parser:   mpu6050SerialParser,
	}, ReaderOptions{
		Open:     func(string, int) (Port, error) { return port, nil },
		OnSample: func(sample Sample, _ int64) { samples <- sample },
	})

	done := make(chan struct{})
	go func() {
		reader.Run(context.Background())
		close(done)
	}()

	require.Eventually(t, func() bool { return len(samples) == 1 }, time.Second, 5*time.Millisecond)
	require.NoError(t, reader.Close())
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)

	sample := <-samples
	assert.Equal(t, "imu", sample.SourceName)
	require.Len(t, sample.Readings, 6)
	assert.InDelta(t, 9.8, *sample.Readings[2].FloatValue, 0.000001)
}

func TestReaderMarksDownAndRetriesOpenWithBackoff(t *testing.T) {
	port := newScriptedPort(readResult{data: []byte(
		`{"device_id":"arduino-001","sensor":"magnetic","value":0}` + "\n",
	)})
	var openCount int
	delays := make(chan time.Duration, 1)
	states := make(chan models.OperatingState, 2)
	samples := make(chan Sample, 1)
	reader := NewReader(testSerialConfig(), ReaderOptions{
		Open: func(string, int) (Port, error) {
			openCount++
			if openCount == 1 {
				return nil, errors.New("serial unavailable")
			}
			return port, nil
		},
		Wait: func(_ context.Context, delay time.Duration) bool {
			delays <- delay
			return true
		},
		OnState:  func(state models.OperatingState) { states <- state },
		OnSample: func(sample Sample, _ int64) { samples <- sample },
	})

	done := make(chan struct{})
	go func() {
		reader.Run(context.Background())
		close(done)
	}()

	require.Eventually(t, func() bool { return len(samples) == 1 }, time.Second, 5*time.Millisecond)
	require.NoError(t, reader.Close())
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)

	assert.Equal(t, 2, openCount)
	assert.Equal(t, time.Second, <-delays)
	assert.Equal(t, models.OperatingState(models.Down), <-states)
	assert.Equal(t, models.OperatingState(models.Up), <-states)
}

func TestReaderResetsBackoffAfterReceivingBytes(t *testing.T) {
	firstPort := newScriptedPort(
		readResult{data: []byte(`{"device_id":"arduino-001","sensor":"temperature","raw":354}` + "\n")},
		readResult{err: io.ErrUnexpectedEOF},
	)
	secondPort := newScriptedPort(readResult{data: []byte(
		`{"device_id":"arduino-001","sensor":"light","value":400}` + "\n",
	)})
	var openCount int
	delays := make(chan time.Duration, 3)
	samples := make(chan Sample, 2)
	reader := NewReader(testSerialConfig(), ReaderOptions{
		Open: func(string, int) (Port, error) {
			openCount++
			switch openCount {
			case 1:
				return nil, errors.New("first open fails")
			case 2:
				return firstPort, nil
			default:
				return secondPort, nil
			}
		},
		Wait: func(_ context.Context, delay time.Duration) bool {
			delays <- delay
			return true
		},
		OnSample: func(sample Sample, _ int64) { samples <- sample },
	})

	done := make(chan struct{})
	go func() {
		reader.Run(context.Background())
		close(done)
	}()

	require.Eventually(t, func() bool { return len(samples) == 2 }, time.Second, 5*time.Millisecond)
	require.NoError(t, reader.Close())
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)

	assert.Equal(t, time.Second, <-delays)
	assert.Equal(t, time.Second, <-delays)
}

func TestReaderCloseInterruptsActivePort(t *testing.T) {
	port := newScriptedPort()
	opened := make(chan struct{})
	reader := NewReader(testSerialConfig(), ReaderOptions{
		Open: func(string, int) (Port, error) {
			close(opened)
			return port, nil
		},
	})
	done := make(chan struct{})
	go func() {
		reader.Run(context.Background())
		close(done)
	}()

	<-opened
	require.NoError(t, reader.Close())
	require.Eventually(t, func() bool {
		select {
		case <-done:
			return true
		default:
			return false
		}
	}, time.Second, 5*time.Millisecond)
	assert.True(t, port.isClosed())
}

func testSerialConfig() SerialConfig {
	return SerialConfig{Port: "/dev/arduino-001", BaudRate: 115200, DeviceID: "arduino-001"}
}

type readResult struct {
	data []byte
	err  error
}

type scriptedPort struct {
	mu      sync.Mutex
	results []readResult
	timeout time.Duration
	closed  chan struct{}
	once    sync.Once
}

func newScriptedPort(results ...readResult) *scriptedPort {
	return &scriptedPort{results: results, closed: make(chan struct{})}
}

func (port *scriptedPort) Read(buffer []byte) (int, error) {
	port.mu.Lock()
	if len(port.results) > 0 {
		result := port.results[0]
		port.results = port.results[1:]
		port.mu.Unlock()
		return copy(buffer, result.data), result.err
	}
	port.mu.Unlock()
	<-port.closed
	return 0, io.EOF
}

func (port *scriptedPort) SetReadTimeout(timeout time.Duration) error {
	port.mu.Lock()
	defer port.mu.Unlock()
	port.timeout = timeout
	return nil
}

func (port *scriptedPort) Close() error {
	port.once.Do(func() { close(port.closed) })
	return nil
}

func (port *scriptedPort) readTimeout() time.Duration {
	port.mu.Lock()
	defer port.mu.Unlock()
	return port.timeout
}

func (port *scriptedPort) isClosed() bool {
	select {
	case <-port.closed:
		return true
	default:
		return false
	}
}
