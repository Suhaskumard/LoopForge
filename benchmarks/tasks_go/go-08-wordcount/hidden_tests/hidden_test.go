package lib

import (
	"reflect"
	"testing"
)

func TestWordCountBasic(t *testing.T) {
	got := WordCount("a b a")
	if !reflect.DeepEqual(got, map[string]int{"a": 2, "b": 1}) {
		t.Fatalf("got %v", got)
	}
}

func TestWordCountCase(t *testing.T) {
	got := WordCount("Go go GO")
	if !reflect.DeepEqual(got, map[string]int{"go": 3}) {
		t.Fatalf("got %v", got)
	}
}

func TestWordCountWhitespace(t *testing.T) {
	got := WordCount("  x\ty\n x  ")
	if !reflect.DeepEqual(got, map[string]int{"x": 2, "y": 1}) {
		t.Fatalf("got %v", got)
	}
}

func TestWordCountEmpty(t *testing.T) {
	got := WordCount("")
	if got == nil || len(got) != 0 {
		t.Fatalf("got %#v", got)
	}
}

func TestWordCountBlank(t *testing.T) {
	got := WordCount("   ")
	if got == nil || len(got) != 0 {
		t.Fatalf("got %#v", got)
	}
}
