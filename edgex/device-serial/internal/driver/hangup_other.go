//go:build !linux

package driver

func disableHangupOnClose(string) error {
	return nil
}
