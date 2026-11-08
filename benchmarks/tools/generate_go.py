"""Generate the Go benchmark tasks (Phase 16): `python benchmarks/tools/generate_go.py`.

Ten small standard-library-only functions, each with a reference solution and >=5 hidden tests.
These were written WITHOUT a Go toolchain on the author's machine: run
`python benchmarks/validate_go.py --require-go` where Go is installed before trusting them.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tasks_go"
GO_MOD = "module example.com/task\n\ngo 1.22\n"


def t(name: str, body: str) -> str:
    return f"func Test{name}(t *testing.T) {{\n{body}}}\n"


TASKS = [
    {
        "slug": "clamp",
        "difficulty": "easy",
        "sig": "func Clamp(value, min, max int) (int, error)",
        "spec": "Return value limited to [min, max]. If min > max return a non-nil error.",
        "imports": ["errors"],
        "ref": """func Clamp(value, min, max int) (int, error) {
	if min > max {
		return 0, errors.New("min greater than max")
	}
	if value < min {
		return min, nil
	}
	if value > max {
		return max, nil
	}
	return value, nil
}
""",
        "test_imports": ["testing"],
        "tests": [
            ("ClampInside", "\tgot, err := Clamp(5, 0, 10)\n\tif err != nil || got != 5 {\n\t\tt.Fatalf(\"got %d, %v\", got, err)\n\t}\n"),
            ("ClampBelow", "\tgot, err := Clamp(-5, 0, 10)\n\tif err != nil || got != 0 {\n\t\tt.Fatalf(\"got %d, %v\", got, err)\n\t}\n"),
            ("ClampAbove", "\tgot, err := Clamp(50, 0, 10)\n\tif err != nil || got != 10 {\n\t\tt.Fatalf(\"got %d, %v\", got, err)\n\t}\n"),
            ("ClampEdges", "\ta, _ := Clamp(0, 0, 10)\n\tb, _ := Clamp(10, 0, 10)\n\tif a != 0 || b != 10 {\n\t\tt.Fatalf(\"got %d and %d\", a, b)\n\t}\n"),
            ("ClampMinGreaterThanMax", "\tif _, err := Clamp(1, 10, 0); err == nil {\n\t\tt.Fatal(\"expected an error\")\n\t}\n"),
        ],
    },
    {
        "slug": "capitalize",
        "difficulty": "easy",
        "sig": "func Capitalize(s string) string",
        "spec": "Upper-case the first character and lower-case the rest (ASCII). An empty string returns an empty string.",
        "imports": ["strings"],
        "ref": """func Capitalize(s string) string {
	if s == "" {
		return ""
	}
	return strings.ToUpper(s[:1]) + strings.ToLower(s[1:])
}
""",
        "test_imports": ["testing"],
        "tests": [
            ("CapitalizeLower", "\tif got := Capitalize(\"hello\"); got != \"Hello\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("CapitalizeUpper", "\tif got := Capitalize(\"WORLD\"); got != \"World\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("CapitalizeEmpty", "\tif got := Capitalize(\"\"); got != \"\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("CapitalizeSingle", "\tif got := Capitalize(\"a\"); got != \"A\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("CapitalizeMixed", "\tif got := Capitalize(\"gO lAnG\"); got != \"Go lang\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
        ],
    },
    {
        "slug": "chunk",
        "difficulty": "easy",
        "sig": "func Chunk(xs []int, size int) ([][]int, error)",
        "spec": "Split xs into consecutive slices of length size (the last may be shorter). size <= 0 returns a non-nil error. An empty xs returns an empty result.",
        "imports": ["errors"],
        "ref": """func Chunk(xs []int, size int) ([][]int, error) {
	if size <= 0 {
		return nil, errors.New("size must be positive")
	}
	out := [][]int{}
	for i := 0; i < len(xs); i += size {
		end := i + size
		if end > len(xs) {
			end = len(xs)
		}
		out = append(out, xs[i:end])
	}
	return out, nil
}
""",
        "test_imports": ["reflect", "testing"],
        "tests": [
            ("ChunkEven", "\tgot, err := Chunk([]int{1, 2, 3, 4}, 2)\n\tif err != nil || !reflect.DeepEqual(got, [][]int{{1, 2}, {3, 4}}) {\n\t\tt.Fatalf(\"got %v, %v\", got, err)\n\t}\n"),
            ("ChunkRemainder", "\tgot, _ := Chunk([]int{1, 2, 3, 4, 5}, 2)\n\tif !reflect.DeepEqual(got, [][]int{{1, 2}, {3, 4}, {5}}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("ChunkEmpty", "\tgot, err := Chunk([]int{}, 3)\n\tif err != nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %v, %v\", got, err)\n\t}\n"),
            ("ChunkLargerThanInput", "\tgot, _ := Chunk([]int{1, 2}, 10)\n\tif !reflect.DeepEqual(got, [][]int{{1, 2}}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("ChunkBadSize", "\tif _, err := Chunk([]int{1}, 0); err == nil {\n\t\tt.Fatal(\"expected an error for size 0\")\n\t}\n\tif _, err := Chunk([]int{1}, -1); err == nil {\n\t\tt.Fatal(\"expected an error for size -1\")\n\t}\n"),
        ],
    },
    {
        "slug": "uniq",
        "difficulty": "easy",
        "sig": "func Uniq(xs []int) []int",
        "spec": "Remove duplicates, keeping the first occurrence of each value and the original order. An empty input returns an empty (non-nil) slice.",
        "imports": [],
        "ref": """func Uniq(xs []int) []int {
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
""",
        "test_imports": ["reflect", "testing"],
        "tests": [
            ("UniqBasic", "\tif got := Uniq([]int{1, 2, 2, 3, 1}); !reflect.DeepEqual(got, []int{1, 2, 3}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("UniqKeepsOrder", "\tif got := Uniq([]int{3, 1, 3, 2, 1}); !reflect.DeepEqual(got, []int{3, 1, 2}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("UniqEmpty", "\tgot := Uniq([]int{})\n\tif got == nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %#v\", got)\n\t}\n"),
            ("UniqAllSame", "\tif got := Uniq([]int{7, 7, 7}); !reflect.DeepEqual(got, []int{7}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("UniqNoDuplicates", "\tif got := Uniq([]int{1, 2, 3}); !reflect.DeepEqual(got, []int{1, 2, 3}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
        ],
    },
    {
        "slug": "reverse",
        "difficulty": "easy",
        "sig": "func Reverse(s string) string",
        "spec": "Return s reversed by Unicode characters (runes), not bytes.",
        "imports": [],
        "ref": """func Reverse(s string) string {
	r := []rune(s)
	for i, j := 0, len(r)-1; i < j; i, j = i+1, j-1 {
		r[i], r[j] = r[j], r[i]
	}
	return string(r)
}
""",
        "test_imports": ["testing"],
        "tests": [
            ("ReverseBasic", "\tif got := Reverse(\"abc\"); got != \"cba\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("ReverseEmpty", "\tif got := Reverse(\"\"); got != \"\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("ReverseSingle", "\tif got := Reverse(\"x\"); got != \"x\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("ReverseUnicode", "\tif got := Reverse(\"héllo\"); got != \"olléh\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
            ("ReverseTwice", "\tif got := Reverse(Reverse(\"LoopForge\")); got != \"LoopForge\" {\n\t\tt.Fatalf(\"got %q\", got)\n\t}\n"),
        ],
    },
    {
        "slug": "average",
        "difficulty": "easy",
        "sig": "func Average(xs []float64) (float64, error)",
        "spec": "Return the arithmetic mean of xs. An empty slice returns a non-nil error.",
        "imports": ["errors"],
        "ref": """func Average(xs []float64) (float64, error) {
	if len(xs) == 0 {
		return 0, errors.New("empty input")
	}
	sum := 0.0
	for _, x := range xs {
		sum += x
	}
	return sum / float64(len(xs)), nil
}
""",
        "test_imports": ["testing"],
        "tests": [
            ("AverageBasic", "\tgot, err := Average([]float64{1, 2, 3})\n\tif err != nil || got != 2 {\n\t\tt.Fatalf(\"got %v, %v\", got, err)\n\t}\n"),
            ("AverageSingle", "\tgot, err := Average([]float64{4.5})\n\tif err != nil || got != 4.5 {\n\t\tt.Fatalf(\"got %v, %v\", got, err)\n\t}\n"),
            ("AverageNegative", "\tgot, _ := Average([]float64{-2, 2})\n\tif got != 0 {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("AverageFraction", "\tgot, _ := Average([]float64{1, 2})\n\tif got != 1.5 {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("AverageEmpty", "\tif _, err := Average([]float64{}); err == nil {\n\t\tt.Fatal(\"expected an error\")\n\t}\n"),
        ],
    },
    {
        "slug": "palindrome",
        "difficulty": "medium",
        "sig": "func IsPalindrome(s string) bool",
        "spec": "Report whether s reads the same forwards and backwards, ignoring case and ignoring every character that is not an ASCII letter or digit. The empty string is a palindrome.",
        "imports": ["strings"],
        "ref": """func IsPalindrome(s string) bool {
	var clean []byte
	for _, c := range []byte(strings.ToLower(s)) {
		if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') {
			clean = append(clean, c)
		}
	}
	for i, j := 0, len(clean)-1; i < j; i, j = i+1, j-1 {
		if clean[i] != clean[j] {
			return false
		}
	}
	return true
}
""",
        "test_imports": ["testing"],
        "tests": [
            ("PalindromeSimple", "\tif !IsPalindrome(\"racecar\") {\n\t\tt.Fatal(\"racecar is a palindrome\")\n\t}\n"),
            ("PalindromeSentence", "\tif !IsPalindrome(\"A man, a plan, a canal: Panama\") {\n\t\tt.Fatal(\"sentence palindrome\")\n\t}\n"),
            ("PalindromeNot", "\tif IsPalindrome(\"hello\") {\n\t\tt.Fatal(\"hello is not a palindrome\")\n\t}\n"),
            ("PalindromeEmpty", "\tif !IsPalindrome(\"\") {\n\t\tt.Fatal(\"empty string is a palindrome\")\n\t}\n"),
            ("PalindromeDigits", "\tif !IsPalindrome(\"12321\") || IsPalindrome(\"12345\") {\n\t\tt.Fatal(\"digit handling\")\n\t}\n"),
        ],
    },
    {
        "slug": "wordcount",
        "difficulty": "medium",
        "sig": "func WordCount(s string) map[string]int",
        "spec": "Count how often each word occurs. Words are separated by any whitespace and compared case-insensitively (keys are lower-case). An empty or blank string returns an empty, non-nil map.",
        "imports": ["strings"],
        "ref": """func WordCount(s string) map[string]int {
	counts := map[string]int{}
	for _, w := range strings.Fields(strings.ToLower(s)) {
		counts[w]++
	}
	return counts
}
""",
        "test_imports": ["reflect", "testing"],
        "tests": [
            ("WordCountBasic", "\tgot := WordCount(\"a b a\")\n\tif !reflect.DeepEqual(got, map[string]int{\"a\": 2, \"b\": 1}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("WordCountCase", "\tgot := WordCount(\"Go go GO\")\n\tif !reflect.DeepEqual(got, map[string]int{\"go\": 3}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("WordCountWhitespace", "\tgot := WordCount(\"  x\\ty\\n x  \")\n\tif !reflect.DeepEqual(got, map[string]int{\"x\": 2, \"y\": 1}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("WordCountEmpty", "\tgot := WordCount(\"\")\n\tif got == nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %#v\", got)\n\t}\n"),
            ("WordCountBlank", "\tgot := WordCount(\"   \")\n\tif got == nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %#v\", got)\n\t}\n"),
        ],
    },
    {
        "slug": "parsekv",
        "difficulty": "medium",
        "sig": "func ParseKV(s string) (map[string]string, error)",
        "spec": "Parse \"key=value\" pairs separated by semicolons, trimming spaces around keys and values (e.g. \"a=1; b=2\"). An empty string returns an empty, non-nil map. A non-empty item without \"=\" or with an empty key returns a non-nil error. If a key repeats, the last value wins.",
        "imports": ["errors", "strings"],
        "ref": """func ParseKV(s string) (map[string]string, error) {
	out := map[string]string{}
	if strings.TrimSpace(s) == "" {
		return out, nil
	}
	for _, item := range strings.Split(s, ";") {
		item = strings.TrimSpace(item)
		if item == "" {
			continue
		}
		parts := strings.SplitN(item, "=", 2)
		if len(parts) != 2 {
			return nil, errors.New("missing '=' in item")
		}
		key := strings.TrimSpace(parts[0])
		if key == "" {
			return nil, errors.New("empty key")
		}
		out[key] = strings.TrimSpace(parts[1])
	}
	return out, nil
}
""",
        "test_imports": ["reflect", "testing"],
        "tests": [
            ("ParseKVBasic", "\tgot, err := ParseKV(\"a=1;b=2\")\n\tif err != nil || !reflect.DeepEqual(got, map[string]string{\"a\": \"1\", \"b\": \"2\"}) {\n\t\tt.Fatalf(\"got %v, %v\", got, err)\n\t}\n"),
            ("ParseKVTrims", "\tgot, _ := ParseKV(\" a = 1 ; b = two \")\n\tif !reflect.DeepEqual(got, map[string]string{\"a\": \"1\", \"b\": \"two\"}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("ParseKVEmpty", "\tgot, err := ParseKV(\"\")\n\tif err != nil || got == nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %#v, %v\", got, err)\n\t}\n"),
            ("ParseKVMalformed", "\tif _, err := ParseKV(\"a=1;oops\"); err == nil {\n\t\tt.Fatal(\"expected an error\")\n\t}\n\tif _, err := ParseKV(\"=1\"); err == nil {\n\t\tt.Fatal(\"expected an error for an empty key\")\n\t}\n"),
            ("ParseKVLastWins", "\tgot, _ := ParseKV(\"a=1;a=2\")\n\tif got[\"a\"] != \"2\" {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
        ],
    },
    {
        "slug": "fizzbuzz",
        "difficulty": "easy",
        "sig": "func FizzBuzz(n int) []string",
        "spec": "Return the numbers 1..n as strings, replacing multiples of 3 with \"Fizz\", multiples of 5 with \"Buzz\" and multiples of both with \"FizzBuzz\". n <= 0 returns an empty (non-nil) slice.",
        "imports": ["strconv"],
        "ref": """func FizzBuzz(n int) []string {
	out := []string{}
	for i := 1; i <= n; i++ {
		switch {
		case i%15 == 0:
			out = append(out, "FizzBuzz")
		case i%3 == 0:
			out = append(out, "Fizz")
		case i%5 == 0:
			out = append(out, "Buzz")
		default:
			out = append(out, strconv.Itoa(i))
		}
	}
	return out
}
""",
        "test_imports": ["reflect", "testing"],
        "tests": [
            ("FizzBuzzFive", "\tif got := FizzBuzz(5); !reflect.DeepEqual(got, []string{\"1\", \"2\", \"Fizz\", \"4\", \"Buzz\"}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("FizzBuzzFifteen", "\tgot := FizzBuzz(15)\n\tif len(got) != 15 || got[14] != \"FizzBuzz\" {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("FizzBuzzZero", "\tgot := FizzBuzz(0)\n\tif got == nil || len(got) != 0 {\n\t\tt.Fatalf(\"got %#v\", got)\n\t}\n"),
            ("FizzBuzzNegative", "\tif got := FizzBuzz(-3); len(got) != 0 {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
            ("FizzBuzzOne", "\tif got := FizzBuzz(1); !reflect.DeepEqual(got, []string{\"1\"}) {\n\t\tt.Fatalf(\"got %v\", got)\n\t}\n"),
        ],
    },
]


def source(imports: list[str], body: str, package: str = "lib") -> str:
    head = f"package {package}\n\n"
    if imports:
        head += "import (\n" + "".join(f'\t"{i}"\n' for i in imports) + ")\n\n"
    return head + body


def main() -> None:
    for n, task in enumerate(TASKS, start=1):
        name = f"go-{n:02d}-{task['slug']}"
        d = OUT / name
        module = f"lib/{task['slug']}.go"
        (d / "reference" / "lib").mkdir(parents=True, exist_ok=True)
        (d / "hidden_tests").mkdir(parents=True, exist_ok=True)
        (d / "reference" / "go.mod").write_text(GO_MOD, encoding="utf-8", newline="\n")
        (d / "reference" / module).write_text(
            source(task["imports"], task["ref"]), encoding="utf-8", newline="\n"
        )
        tests = "\n".join(t(nm, body) for nm, body in task["tests"])
        (d / "hidden_tests" / "hidden_test.go").write_text(
            source(task["test_imports"], tests), encoding="utf-8", newline="\n"
        )
        requirement = (
            "Create a small Go module using only the standard library. Use exactly this go.mod:\n"
            f"{GO_MOD}\nPut the implementation in `{module}` (package `lib`) and your own tests in "
            f"`lib/{task['slug']}_test.go` (package `lib`, `go test`). No third-party modules.\n\n"
            f"SPEC: Implement `{task['sig']}`. {task['spec']}"
        )
        meta = {
            "id": name,
            "category": "go",
            "language": "go",
            "difficulty": task["difficulty"],
            "requirement": requirement,
            "acceptance_criteria": [f"{task['sig']}: {task['spec']}"],
            "source": "none",
            "module": module,
            "signature": task["sig"],
            "rubric": {
                "primary": "all hidden tests pass (hidden_pass_rate == 1.0)",
                "notes": "hidden tests run in a separate, independent step; the agents' own tests do not count",
            },
        }
        (d / "task.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(TASKS)} tasks to {OUT}")


if __name__ == "__main__":
    main()
