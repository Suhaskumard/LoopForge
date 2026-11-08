package lib

import (
	"reflect"
	"testing"
)

func TestChunkEven(t *testing.T) {
	got, err := Chunk([]int{1, 2, 3, 4}, 2)
	if err != nil || !reflect.DeepEqual(got, [][]int{{1, 2}, {3, 4}}) {
		t.Fatalf("got %v, %v", got, err)
	}
}

func TestChunkRemainder(t *testing.T) {
	got, _ := Chunk([]int{1, 2, 3, 4, 5}, 2)
	if !reflect.DeepEqual(got, [][]int{{1, 2}, {3, 4}, {5}}) {
		t.Fatalf("got %v", got)
	}
}

func TestChunkEmpty(t *testing.T) {
	got, err := Chunk([]int{}, 3)
	if err != nil || len(got) != 0 {
		t.Fatalf("got %v, %v", got, err)
	}
}

func TestChunkLargerThanInput(t *testing.T) {
	got, _ := Chunk([]int{1, 2}, 10)
	if !reflect.DeepEqual(got, [][]int{{1, 2}}) {
		t.Fatalf("got %v", got)
	}
}

func TestChunkBadSize(t *testing.T) {
	if _, err := Chunk([]int{1}, 0); err == nil {
		t.Fatal("expected an error for size 0")
	}
	if _, err := Chunk([]int{1}, -1); err == nil {
		t.Fatal("expected an error for size -1")
	}
}
