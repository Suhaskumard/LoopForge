package lib

import (
	"testing"
)

func TestClampInside(t *testing.T) {
	got, err := Clamp(5, 0, 10)
	if err != nil || got != 5 {
		t.Fatalf("got %d, %v", got, err)
	}
}

func TestClampBelow(t *testing.T) {
	got, err := Clamp(-5, 0, 10)
	if err != nil || got != 0 {
		t.Fatalf("got %d, %v", got, err)
	}
}

func TestClampAbove(t *testing.T) {
	got, err := Clamp(50, 0, 10)
	if err != nil || got != 10 {
		t.Fatalf("got %d, %v", got, err)
	}
}

func TestClampEdges(t *testing.T) {
	a, _ := Clamp(0, 0, 10)
	b, _ := Clamp(10, 0, 10)
	if a != 0 || b != 10 {
		t.Fatalf("got %d and %d", a, b)
	}
}

func TestClampMinGreaterThanMax(t *testing.T) {
	if _, err := Clamp(1, 10, 0); err == nil {
		t.Fatal("expected an error")
	}
}
