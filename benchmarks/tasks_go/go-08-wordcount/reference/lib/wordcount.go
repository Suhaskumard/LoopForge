package lib

import (
	"strings"
)

func WordCount(s string) map[string]int {
	counts := map[string]int{}
	for _, w := range strings.Fields(strings.ToLower(s)) {
		counts[w]++
	}
	return counts
}
