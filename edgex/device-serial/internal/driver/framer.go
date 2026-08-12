package driver

type LineFramer struct {
	maxBytes   int
	buffer     []byte
	discarding bool
}

func NewLineFramer(maxBytes int) *LineFramer {
	if maxBytes <= 0 {
		panic("maxBytes must be positive")
	}
	return &LineFramer{
		maxBytes: maxBytes,
		buffer:   make([]byte, 0, maxBytes),
	}
}

func (framer *LineFramer) Push(chunk []byte) [][]byte {
	lines := make([][]byte, 0)
	for _, current := range chunk {
		if framer.discarding {
			if current == '\n' {
				framer.discarding = false
			}
			continue
		}

		if current == '\n' {
			line := framer.buffer
			if len(line) > 0 && line[len(line)-1] == '\r' {
				line = line[:len(line)-1]
			}
			if len(line) > 0 {
				lines = append(lines, append([]byte(nil), line...))
			}
			framer.buffer = framer.buffer[:0]
			continue
		}

		if len(framer.buffer) >= framer.maxBytes {
			framer.buffer = framer.buffer[:0]
			framer.discarding = true
			continue
		}
		framer.buffer = append(framer.buffer, current)
	}
	return lines
}
