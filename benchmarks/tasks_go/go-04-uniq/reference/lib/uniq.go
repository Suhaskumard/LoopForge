package lib

func Uniq(xs []int) []int {
	seen := map[int]bool{}
	out := []int{}
	for _, x := range xs {
		if !seen[x] {
			seen[x] = true
			out = append(out, x)
		}
	}
	return out
}
