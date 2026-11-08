package lib

import (
	"testing"
)

func TestAverageBasic(t *testing.T) {
	got, err := Average([]float64{1, 2, 3})
	if err != nil || got != 2 {
		t.Fatalf("got %v, %v", got, err)
	}
}

func TestAverageSingle(t *testing.T) {
	got, err := Average([]float64{4.5})
	if err != nil || got != 4.5 {
		t.Fatalf("got %v, %v", got, err)
	}
}

func TestAverageNegative(t *testing.T) {
	got, _ := Average([]float64{-2, 2})
	if got != 0 {
		t.Fatalf("got %v", got)
	}
}

func TestAverageFraction(t *testing.T) {
	got, _ := Average([]float64{1, 2})
	if got != 1.5 {
		t.Fatalf("got %v", got)
	}
}

func TestAverageEmpty(t *testing.T) {
	if _, err := Average([]float64{}); err == nil {
		t.Fatal("expected an error")
	}
}
