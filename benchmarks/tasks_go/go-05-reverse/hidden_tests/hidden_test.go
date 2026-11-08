package lib

import (
	"testing"
)

func TestReverseBasic(t *testing.T) {
	if got := Reverse("abc"); got != "cba" {
		t.Fatalf("got %q", got)
	}
}

func TestReverseEmpty(t *testing.T) {
	if got := Reverse(""); got != "" {
		t.Fatalf("got %q", got)
	}
}

func TestReverseSingle(t *testing.T) {
	if got := Reverse("x"); got != "x" {
		t.Fatalf("got %q", got)
	}
}

func TestReverseUnicode(t *testing.T) {
	if got := Reverse("héllo"); got != "olléh" {
		t.Fatalf("got %q", got)
	}
}

func TestReverseTwice(t *testing.T) {
	if got := Reverse(Reverse("LoopForge")); got != "LoopForge" {
		t.Fatalf("got %q", got)
	}
}
