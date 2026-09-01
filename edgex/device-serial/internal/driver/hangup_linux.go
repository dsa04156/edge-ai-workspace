//go:build linux

package driver

import (
	"fmt"

	"golang.org/x/sys/unix"
)

func disableHangupOnClose(path string) (resultErr error) {
	fileDescriptor, err := unix.Open(
		path,
		unix.O_RDWR|unix.O_NOCTTY|unix.O_NONBLOCK,
		0,
	)
	if err != nil {
		return fmt.Errorf("open serial port for termios preparation: %w", err)
	}
	defer func() {
		if closeErr := unix.Close(fileDescriptor); closeErr != nil && resultErr == nil {
			resultErr = fmt.Errorf("close prepared serial port: %w", closeErr)
		}
	}()

	settings, err := unix.IoctlGetTermios(fileDescriptor, unix.TCGETS)
	if err != nil {
		return fmt.Errorf("read serial termios: %w", err)
	}
	clearHangupOnCloseFlag(settings)
	if err := unix.IoctlSetTermios(fileDescriptor, unix.TCSETS, settings); err != nil {
		return fmt.Errorf("disable serial HUPCL: %w", err)
	}
	return nil
}

func clearHangupOnCloseFlag(settings *unix.Termios) {
	settings.Cflag &^= unix.HUPCL
}
