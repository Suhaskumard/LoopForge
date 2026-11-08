package lib

import (
	"reflect"
	"testing"
)

func TestParseKVBasic(t *testing.T) {
	got, err := ParseKV("a=1;b=2")
	if err != nil || !reflect.DeepEqual(got, map[string]string{"a": "1", "b": "2"}) {
		t.Fatalf("got %v, %v", got, err)
	}
}

func TestParseKVTrims(t *testing.T) {
	got, _ := ParseKV(" a = 1 ; b = two ")
	if !reflect.DeepEqual(got, map[string]string{"a": "1", "b": "two"}) {
		t.Fatalf("got %v", got)
	}
}

func TestParseKVEmpty(t *testing.T) {
	got, err := ParseKV("")
	if err != nil || got == nil || len(got) != 0 {
		t.Fatalf("got %#v, %v", got, err)
	}
}

func TestParseKVMalformed(t *testing.T) {
	if _, err := ParseKV("a=1;oops"); err == nil {
		t.Fatal("expected an error")
	}
	if _, err := ParseKV("=1"); err == nil {
		t.Fatal("expected an error for an empty key")
	}
}

func TestParseKVLastWins(t *testing.T) {
	got, _ := ParseKV("a=1;a=2")
	if got["a"] != "2" {
		t.Fatalf("got %v", got)
	}
}
