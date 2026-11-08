package lib

import (
	"reflect"
	"testing"
)

func TestUniqBasic(t *testing.T) {
	if got := Uniq([]int{1, 2, 2, 3, 1}); !reflect.DeepEqual(got, []int{1, 2, 3}) {
		t.Fatalf("got %v", got)
	}
}

func TestUniqKeepsOrder(t *testing.T) {
	if got := Uniq([]int{3, 1, 3, 2, 1}); !reflect.DeepEqual(got, []int{3, 1, 2}) {
		t.Fatalf("got %v", got)
	}
}

func TestUniqEmpty(t *testing.T) {
	got := Uniq([]int{})
	if got == nil || len(got) != 0 {
		t.Fatalf("got %#v", got)
	}
}

func TestUniqAllSame(t *testing.T) {
	if got := Uniq([]int{7, 7, 7}); !reflect.DeepEqual(got, []int{7}) {
		t.Fatalf("got %v", got)
	}
}

func TestUniqNoDuplicates(t *testing.T) {
	if got := Uniq([]int{1, 2, 3}); !reflect.DeepEqual(got, []int{1, 2, 3}) {
		t.Fatalf("got %v", got)
	}
}
