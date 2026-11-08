package lib

import (
	"errors"
)

func Chunk(xs []int, size int) ([][]int, error) {
	if size <= 0 {
		return nil, errors.New("size must be positive")
	}
	out := [][]int{}
	for i := 0; i < len(xs); i += size {
		end := i + size
		if end > len(xs) {
			end = len(xs)
		}
		out = append(out, xs[i:end])
	}
	return out, nil
}
