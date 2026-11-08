package lib

import (
	"reflect"
	"testing"
)

func TestFizzBuzzFive(t *testing.T) {
	if got := FizzBuzz(5); !reflect.DeepEqual(got, []string{"1", "2", "Fizz", "4", "Buzz"}) {
		t.Fatalf("got %v", got)
	}
}

func TestFizzBuzzFifteen(t *testing.T) {
	got := FizzBuzz(15)
	if len(got) != 15 || got[14] != "FizzBuzz" {
		t.Fatalf("got %v", got)
	}
}

func TestFizzBuzzZero(t *testing.T) {
	got := FizzBuzz(0)
	if got == nil || len(got) != 0 {
		t.Fatalf("got %#v", got)
	}
}

func TestFizzBuzzNegative(t *testing.T) {
	if got := FizzBuzz(-3); len(got) != 0 {
		t.Fatalf("got %v", got)
	}
}

func TestFizzBuzzOne(t *testing.T) {
	if got := FizzBuzz(1); !reflect.DeepEqual(got, []string{"1"}) {
		t.Fatalf("got %v", got)
	}
}
