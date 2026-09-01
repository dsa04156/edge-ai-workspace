//go:build linux

package driver

import (
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"go.bug.st/serial"
	"golang.org/x/sys/unix"
)

func TestClearHangupOnCloseFlagPreservesOtherControlFlags(t *testing.T) {
	settings := &unix.Termios{Cflag: unix.HUPCL | unix.CLOCAL | unix.CREAD | unix.CS8}

	clearHangupOnCloseFlag(settings)

	assert.Zero(t, settings.Cflag&unix.HUPCL)
	assert.NotZero(t, settings.Cflag&unix.CLOCAL)
	assert.NotZero(t, settings.Cflag&unix.CREAD)
	assert.NotZero(t, settings.Cflag&unix.CS8)
}

func TestOpenConfiguredSerialPreparesPortBeforeLibraryOpen(t *testing.T) {
	var calls []string
	port := newScriptedPort()

	opened, err := openConfiguredSerial(
		"/dev/arduino-001",
		115200,
		func(path string) error {
			calls = append(calls, "prepare:"+path)
			return nil
		},
		func(path string, mode *serial.Mode) (Port, error) {
			calls = append(calls, "open:"+path)
			assert.Equal(t, 115200, mode.BaudRate)
			assert.Equal(t, 8, mode.DataBits)
			assert.Equal(t, serial.NoParity, mode.Parity)
			assert.Equal(t, serial.OneStopBit, mode.StopBits)
			assert.Nil(t, mode.InitialStatusBits)
			return port, nil
		},
	)

	require.NoError(t, err)
	assert.Same(t, port, opened)
	assert.Equal(t, []string{
		"prepare:/dev/arduino-001",
		"open:/dev/arduino-001",
	}, calls)
}

func TestOpenConfiguredSerialDoesNotOpenWhenPreparationFails(t *testing.T) {
	prepareErr := errors.New("termios unavailable")
	openCalled := false

	opened, err := openConfiguredSerial(
		"/dev/arduino-001",
		115200,
		func(string) error { return prepareErr },
		func(string, *serial.Mode) (Port, error) {
			openCalled = true
			return nil, nil
		},
	)

	require.ErrorIs(t, err, prepareErr)
	assert.Nil(t, opened)
	assert.False(t, openCalled)
}
