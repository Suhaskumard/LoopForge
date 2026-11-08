package lib

import (
	"testing"
)

func TestCapitalizeLower(t *testing.T) {
	if got := Capitalize("hello"); got != "Hello" {
		t.Fatalf("got %q", got)
	}
}

func TestCapitalizeUpper(t *testing.T) {
	if got := Capitalize("WORLD"); got != "World" {
		t.Fatalf("got %q", got)
	}
}

func TestCapitalizeEmpty(t *testing.T) {
	if got := Capitalize(""); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestCapitalizeSingle(t *testing.T) {
	if got := Capitalize("a"); got != "A" {
		t.Fatalf("got %q", got)
	}
}

func TestCapitalizeMixed(t *testing.T) {
	if got := Capitalize("gO lAnG"); got != "Go lang" {
		t.Fatalf("got %q", got)
	}
}
