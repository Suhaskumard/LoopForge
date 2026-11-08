package lib

import (
	"errors"
)

func Clamp(value, min, max int) (int, error) {
	if min > max {
		return 0, errors.New("min greater than max")
	}
	if value < min {
		return min, nil
	}
	if value > max {
		return max, nil
	}
	return value, nil
}
