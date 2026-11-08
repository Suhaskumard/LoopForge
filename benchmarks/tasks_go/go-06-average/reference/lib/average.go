package lib

import (
	"errors"
)

func Average(xs []float64) (float64, error) {
	if len(xs) == 0 {
		return 0, errors.New("empty input")
	}
	sum := 0.0
	for _, x := range xs {
		sum += x
	}
	return sum / float64(len(xs)), nil
}
