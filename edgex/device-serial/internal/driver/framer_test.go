package driver

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestLineFramerReassemblesCRLFAcrossChunks(t *testing.T) {
	framer := NewLineFramer(32)

	assert.Empty(t, framer.Push([]byte("first\r")))
	assert.Equal(t, [][]byte{[]byte("first"), []byte("second")}, framer.Push([]byte("\nsecond\n")))
}

func TestLineFramerReturnsMultipleLinesAndIgnoresEmptyLines(t *testing.T) {
	framer := NewLineFramer(32)

	assert.Equal(t, [][]byte{[]byte("one"), []byte("two")}, framer.Push([]byte("\none\n\r\ntwo\r\n")))
}

func TestLineFramerAcceptsLineAtLimit(t *testing.T) {
	framer := NewLineFramer(5)

	assert.Equal(t, [][]byte{[]byte("12345")}, framer.Push([]byte("12345\n")))
}

func TestLineFramerDropsWholeOversizeLineAndRecovers(t *testing.T) {
	framer := NewLineFramer(5)

	assert.Empty(t, framer.Push([]byte("123456")))
	assert.Equal(t, [][]byte{[]byte("ok")}, framer.Push([]byte("789\nok\n")))
}

func TestLineFramerDoesNotLeakPreviousChunkStorage(t *testing.T) {
	framer := NewLineFramer(32)
	chunk := []byte("stable\n")

	lines := framer.Push(chunk)
	chunk[0] = 'X'

	assert.Equal(t, []byte("stable"), lines[0])
}
