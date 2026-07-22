package localcache

import (
	"sort"
	"time"
)

type sampleRing[T any] struct {
	values      []Sample[T]
	head        int
	size        int
	maxCapacity int
}

func newSampleRing[T any](maxCapacity int) *sampleRing[T] {
	return &sampleRing[T]{maxCapacity: maxCapacity}
}

func (ring *sampleRing[T]) capacity() int {
	return len(ring.values)
}

func (ring *sampleRing[T]) append(sample Sample[T], maxAge time.Duration) (int, int) {
	if ring.size > 0 && sample.Origin < ring.at(ring.size-1).Origin {
		return ring.appendOutOfOrder(sample, maxAge)
	}

	ageEvicted := ring.dropBefore(sample.Origin - maxAge.Nanoseconds())
	if ring.size < ring.maxCapacity {
		ring.ensureCapacity(ring.size + 1)
		index := (ring.head + ring.size) % len(ring.values)
		ring.values[index] = sample
		ring.size++
		return ageEvicted, 0
	}

	ring.values[ring.head] = sample
	ring.head = (ring.head + 1) % len(ring.values)
	return ageEvicted, 1
}

func (ring *sampleRing[T]) appendOutOfOrder(
	sample Sample[T],
	maxAge time.Duration,
) (int, int) {
	ordered := ring.ordered()
	ordered = append(ordered, sample)
	sort.SliceStable(ordered, func(left int, right int) bool {
		return ordered[left].Origin < ordered[right].Origin
	})

	cutoff := ordered[len(ordered)-1].Origin - maxAge.Nanoseconds()
	firstRetained := sort.Search(len(ordered), func(index int) bool {
		return ordered[index].Origin >= cutoff
	})
	ageEvicted := firstRetained
	ordered = ordered[firstRetained:]

	limitEvicted := 0
	if len(ordered) > ring.maxCapacity {
		limitEvicted = len(ordered) - ring.maxCapacity
		ordered = ordered[limitEvicted:]
	}
	ring.ensureCapacity(len(ordered))
	ring.rebuild(ordered, ring.capacity())
	return ageEvicted, limitEvicted
}

func (ring *sampleRing[T]) setMaxCapacity(maxCapacity int) int {
	if maxCapacity < 1 {
		panic("sample ring capacity must be positive")
	}
	ring.maxCapacity = maxCapacity
	if ring.capacity() <= maxCapacity && ring.size <= maxCapacity {
		return 0
	}

	ordered := ring.ordered()
	evicted := 0
	if len(ordered) > maxCapacity {
		evicted = len(ordered) - maxCapacity
		ordered = ordered[evicted:]
	}
	targetCapacity := ring.capacity()
	if targetCapacity > maxCapacity {
		targetCapacity = maxCapacity
	}
	if targetCapacity < len(ordered) {
		targetCapacity = len(ordered)
	}
	ring.rebuild(ordered, targetCapacity)
	return evicted
}

func (ring *sampleRing[T]) ensureCapacity(required int) {
	if required <= ring.capacity() {
		return
	}
	capacity := ring.capacity()
	if capacity == 0 {
		capacity = 1
	}
	for capacity < required {
		capacity *= 2
		if capacity >= ring.maxCapacity {
			capacity = ring.maxCapacity
			break
		}
	}
	ring.rebuild(ring.ordered(), capacity)
}

func (ring *sampleRing[T]) dropBefore(cutoff int64) int {
	evicted := 0
	for ring.size > 0 && ring.at(0).Origin < cutoff {
		var zero Sample[T]
		ring.values[ring.head] = zero
		ring.head = (ring.head + 1) % len(ring.values)
		ring.size--
		evicted++
	}
	if ring.size == 0 {
		ring.head = 0
	}
	return evicted
}

func (ring *sampleRing[T]) at(offset int) Sample[T] {
	return ring.values[(ring.head+offset)%len(ring.values)]
}

func (ring *sampleRing[T]) ordered() []Sample[T] {
	result := make([]Sample[T], ring.size)
	for index := 0; index < ring.size; index++ {
		result[index] = ring.at(index)
	}
	return result
}

func (ring *sampleRing[T]) query(from int64, to int64, limit int) []Sample[T] {
	ordered := ring.ordered()
	start := sort.Search(len(ordered), func(index int) bool {
		return ordered[index].Origin >= from
	})
	end := sort.Search(len(ordered), func(index int) bool {
		return ordered[index].Origin > to
	})
	if start >= end {
		return []Sample[T]{}
	}
	if end-start > limit {
		start = end - limit
	}
	result := make([]Sample[T], end-start)
	copy(result, ordered[start:end])
	return result
}

func (ring *sampleRing[T]) rebuild(samples []Sample[T], capacity int) {
	if capacity == 0 {
		ring.values = nil
		ring.head = 0
		ring.size = 0
		return
	}
	values := make([]Sample[T], capacity)
	copy(values, samples)
	ring.values = values
	ring.head = 0
	ring.size = len(samples)
}
