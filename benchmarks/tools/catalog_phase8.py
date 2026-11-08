"""Phase 8 benchmark catalog: 10 repository-input (bug in an existing repo) + 10 JavaScript tasks.

Repo tasks: `repo` (broken code + its own passing visible tests), `reference` (fixed tree) and
hidden tests that fail on the repo and pass on the reference. The broken code is NOT pasted into the
requirement: the agents must read it from the imported repository (removes ADR-0012's limitation).

JS tasks: greenfield CommonJS modules checked by hidden Jest tests.
Run `python benchmarks/tools/generate_phase8.py` to (re)write benchmarks/tasks_phase8/.
"""

# (id, module, symptom, spec, broken_src, fixed_src, visible_test_body, hidden_test_body)
# Tests import with: from lib.<module> import <names>
REPO_TASKS = [
    dict(
        id="repo-01-slugify", mod="slugify", difficulty="easy",
        symptom="`slugify('Hello,   World!')` returns 'hello,---world!' instead of 'hello-world'.",
        spec="Lowercase; every run of non-alphanumeric characters becomes ONE '-'; no leading/trailing '-'.",
        broken='import re\n\n\ndef slugify(text):\n    return re.sub(r"\\s", "-", text.lower())\n',
        fixed='import re\n\n\ndef slugify(text):\n    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n',
        visible='from lib.slugify import slugify\n\n\ndef test_simple():\n    assert slugify("hello") == "hello"\n\n\ndef test_space():\n    assert slugify("a b") == "a-b"\n',
        hidden='from lib.slugify import slugify\n\n\ndef test_punctuation():\n    assert slugify("Hello,   World!") == "hello-world"\n\n\ndef test_edges():\n    assert slugify("  --Hi--  ") == "hi"\n\n\ndef test_digits():\n    assert slugify("Python 3.12") == "python-3-12"\n\n\ndef test_empty():\n    assert slugify("!!!") == ""\n\n\ndef test_plain():\n    assert slugify("abc") == "abc"\n',
    ),
    dict(
        id="repo-02-median", mod="stats", difficulty="easy",
        symptom="`median([1, 2, 3, 4])` returns 3 instead of 2.5.",
        spec="Median of a non-empty list; for an even count it is the mean of the two middle values. Empty list raises ValueError.",
        broken='def median(values):\n    if not values:\n        raise ValueError("empty")\n    s = sorted(values)\n    return s[len(s) // 2]\n',
        fixed='def median(values):\n    if not values:\n        raise ValueError("empty")\n    s = sorted(values)\n    mid = len(s) // 2\n    if len(s) % 2:\n        return s[mid]\n    return (s[mid - 1] + s[mid]) / 2\n',
        visible='import pytest\nfrom lib.stats import median\n\n\ndef test_odd():\n    assert median([3, 1, 2]) == 2\n\n\ndef test_empty():\n    with pytest.raises(ValueError):\n        median([])\n',
        hidden='import pytest\nfrom lib.stats import median\n\n\ndef test_even():\n    assert median([1, 2, 3, 4]) == 2.5\n\n\ndef test_even_unsorted():\n    assert median([10, 2, 4, 8]) == 6\n\n\ndef test_odd():\n    assert median([5, 1, 3]) == 3\n\n\ndef test_single():\n    assert median([7]) == 7\n\n\ndef test_empty():\n    with pytest.raises(ValueError):\n        median([])\n',
    ),
    dict(
        id="repo-03-chunk", mod="listutil", difficulty="easy",
        symptom="`chunk([1,2,3,4,5], 2)` returns [[1,2],[3,4]] and drops the 5.",
        spec="Split into consecutive chunks of at most n items, keeping the shorter last chunk. n < 1 raises ValueError.",
        broken='def chunk(items, n):\n    if n < 1:\n        raise ValueError("n")\n    return [items[i : i + n] for i in range(0, len(items) - n + 1, n)]\n',
        fixed='def chunk(items, n):\n    if n < 1:\n        raise ValueError("n")\n    return [items[i : i + n] for i in range(0, len(items), n)]\n',
        visible='from lib.listutil import chunk\n\n\ndef test_exact():\n    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]\n\n\ndef test_empty():\n    assert chunk([], 3) == []\n',
        hidden='import pytest\nfrom lib.listutil import chunk\n\n\ndef test_remainder():\n    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\n\n\ndef test_bigger_than_list():\n    assert chunk([1, 2], 5) == [[1, 2]]\n\n\ndef test_exact():\n    assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]\n\n\ndef test_bad_n():\n    with pytest.raises(ValueError):\n        chunk([1], 0)\n\n\ndef test_empty():\n    assert chunk([], 3) == []\n',
    ),
    dict(
        id="repo-04-duration", mod="duration", difficulty="medium",
        symptom="`parse_duration('1h30m')` returns 3600 (the minutes are ignored when hours are present).",
        spec="Parse strings made of <int>h, <int>m, <int>s parts in that order (each optional, at least one) into total seconds. Anything else raises ValueError.",
        broken='import re\n\n\ndef parse_duration(text):\n    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", text)\n    if not text or not m:\n        raise ValueError(text)\n    h, mi, s = (int(g) if g else 0 for g in m.groups())\n    if h:\n        return h * 3600\n    return mi * 60 + s\n',
        fixed='import re\n\n\ndef parse_duration(text):\n    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", text)\n    if not text or not m:\n        raise ValueError(text)\n    h, mi, s = (int(g) if g else 0 for g in m.groups())\n    return h * 3600 + mi * 60 + s\n',
        visible='from lib.duration import parse_duration\n\n\ndef test_seconds():\n    assert parse_duration("45s") == 45\n\n\ndef test_minutes():\n    assert parse_duration("2m") == 120\n',
        hidden='import pytest\nfrom lib.duration import parse_duration\n\n\ndef test_hours_minutes():\n    assert parse_duration("1h30m") == 5400\n\n\ndef test_all_parts():\n    assert parse_duration("1h2m3s") == 3723\n\n\ndef test_hours_only():\n    assert parse_duration("2h") == 7200\n\n\ndef test_minutes_seconds():\n    assert parse_duration("5m10s") == 310\n\n\n@pytest.mark.parametrize("bad", ["", "abc", "1x", "30m1h"])\ndef test_invalid(bad):\n    with pytest.raises(ValueError):\n        parse_duration(bad)\n',
    ),
    dict(
        id="repo-05-palindrome", mod="text", difficulty="easy",
        symptom="`is_palindrome('A man, a plan, a canal: Panama')` returns False.",
        spec="True when the string reads the same forwards and backwards, ignoring case and any non-alphanumeric characters. The empty string is a palindrome.",
        broken='def is_palindrome(text):\n    return text == text[::-1]\n',
        fixed='def is_palindrome(text):\n    cleaned = [c.lower() for c in text if c.isalnum()]\n    return cleaned == cleaned[::-1]\n',
        visible='from lib.text import is_palindrome\n\n\ndef test_true():\n    assert is_palindrome("abba")\n\n\ndef test_false():\n    assert not is_palindrome("abc")\n',
        hidden='from lib.text import is_palindrome\n\n\ndef test_sentence():\n    assert is_palindrome("A man, a plan, a canal: Panama")\n\n\ndef test_case():\n    assert is_palindrome("Racecar")\n\n\ndef test_not():\n    assert not is_palindrome("hello, world")\n\n\ndef test_empty():\n    assert is_palindrome("")\n\n\ndef test_digits():\n    assert is_palindrome("12 21")\n',
    ),
    dict(
        id="repo-06-intervals", mod="intervals", difficulty="medium",
        symptom="`merge_intervals([(1, 2), (2, 3)])` returns [(1, 2), (2, 3)] instead of [(1, 3)].",
        spec="Merge overlapping OR touching closed intervals; input may be unsorted; return a sorted list of tuples; do not mutate the input.",
        broken='def merge_intervals(intervals):\n    out = []\n    for start, end in sorted(intervals):\n        if out and start < out[-1][1]:\n            out[-1] = (out[-1][0], max(out[-1][1], end))\n        else:\n            out.append((start, end))\n    return out\n',
        fixed='def merge_intervals(intervals):\n    out = []\n    for start, end in sorted(intervals):\n        if out and start <= out[-1][1]:\n            out[-1] = (out[-1][0], max(out[-1][1], end))\n        else:\n            out.append((start, end))\n    return out\n',
        visible='from lib.intervals import merge_intervals\n\n\ndef test_overlap():\n    assert merge_intervals([(1, 5), (3, 7)]) == [(1, 7)]\n\n\ndef test_disjoint():\n    assert merge_intervals([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]\n',
        hidden='from lib.intervals import merge_intervals\n\n\ndef test_touching():\n    assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]\n\n\ndef test_unsorted():\n    assert merge_intervals([(5, 6), (1, 2), (2, 4)]) == [(1, 4), (5, 6)]\n\n\ndef test_contained():\n    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]\n\n\ndef test_no_mutation():\n    data = [(3, 4), (1, 3)]\n    merge_intervals(data)\n    assert data == [(3, 4), (1, 3)]\n\n\ndef test_empty():\n    assert merge_intervals([]) == []\n',
    ),
    dict(
        id="repo-07-wordcount", mod="words", difficulty="medium",
        symptom="`word_count('Hi, hi! HI?')` returns {'hi,': 1, 'hi!': 1, 'hi?': 1} instead of {'hi': 3}.",
        spec="Count words case-insensitively; a word is a maximal run of letters, digits or apostrophes; punctuation separates words.",
        broken='def word_count(text):\n    counts = {}\n    for w in text.lower().split():\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n',
        fixed='import re\n\n\ndef word_count(text):\n    counts = {}\n    for w in re.findall(r"[a-z0-9\']+", text.lower()):\n        counts[w] = counts.get(w, 0) + 1\n    return counts\n',
        visible='from lib.words import word_count\n\n\ndef test_basic():\n    assert word_count("a b a") == {"a": 2, "b": 1}\n\n\ndef test_empty():\n    assert word_count("") == {}\n',
        hidden='from lib.words import word_count\n\n\ndef test_punctuation():\n    assert word_count("Hi, hi! HI?") == {"hi": 3}\n\n\ndef test_apostrophe():\n    assert word_count("don\'t stop") == {"don\'t": 1, "stop": 1}\n\n\ndef test_digits():\n    assert word_count("r2d2 r2d2") == {"r2d2": 2}\n\n\ndef test_separators():\n    assert word_count("a-b;c") == {"a": 1, "b": 1, "c": 1}\n\n\ndef test_basic():\n    assert word_count("a b a") == {"a": 2, "b": 1}\n',
    ),
    dict(
        id="repo-08-roman", mod="roman", difficulty="medium",
        symptom="`roman_to_int('IV')` returns 6 and `roman_to_int('MCMXCIV')` returns 2186.",
        spec="Convert a valid roman numeral to int, honouring subtractive pairs (IV, IX, XL, XC, CD, CM). Unknown characters raise ValueError.",
        broken='VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}\n\n\ndef roman_to_int(text):\n    if not text or any(c not in VALUES for c in text):\n        raise ValueError(text)\n    return sum(VALUES[c] for c in text)\n',
        fixed='VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}\n\n\ndef roman_to_int(text):\n    if not text or any(c not in VALUES for c in text):\n        raise ValueError(text)\n    total = 0\n    for i, c in enumerate(text):\n        if i + 1 < len(text) and VALUES[c] < VALUES[text[i + 1]]:\n            total -= VALUES[c]\n        else:\n            total += VALUES[c]\n    return total\n',
        visible='from lib.roman import roman_to_int\n\n\ndef test_simple():\n    assert roman_to_int("VIII") == 8\n\n\ndef test_thousand():\n    assert roman_to_int("MM") == 2000\n',
        hidden='import pytest\nfrom lib.roman import roman_to_int\n\n\ndef test_subtractive():\n    assert roman_to_int("IV") == 4\n    assert roman_to_int("IX") == 9\n\n\ndef test_long():\n    assert roman_to_int("MCMXCIV") == 1994\n\n\ndef test_xl():\n    assert roman_to_int("XLII") == 42\n\n\ndef test_simple():\n    assert roman_to_int("VIII") == 8\n\n\n@pytest.mark.parametrize("bad", ["", "ABC", "iv"])\ndef test_invalid(bad):\n    with pytest.raises(ValueError):\n        roman_to_int(bad)\n',
    ),
    dict(
        id="repo-09-flatten", mod="nested", difficulty="easy",
        symptom="`flatten([1, [2, [3, [4]]]])` returns [1, 2, [3, [4]]].",
        spec="Flatten arbitrarily nested lists/tuples into a single list preserving order. Strings are NOT iterated.",
        broken='def flatten(items):\n    out = []\n    for x in items:\n        if isinstance(x, (list, tuple)):\n            out.extend(x)\n        else:\n            out.append(x)\n    return out\n',
        fixed='def flatten(items):\n    out = []\n    for x in items:\n        if isinstance(x, (list, tuple)):\n            out.extend(flatten(x))\n        else:\n            out.append(x)\n    return out\n',
        visible='from lib.nested import flatten\n\n\ndef test_flat():\n    assert flatten([1, 2]) == [1, 2]\n\n\ndef test_one_level():\n    assert flatten([1, [2, 3]]) == [1, 2, 3]\n',
        hidden='from lib.nested import flatten\n\n\ndef test_deep():\n    assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]\n\n\ndef test_tuples():\n    assert flatten([(1, (2,)), 3]) == [1, 2, 3]\n\n\ndef test_strings_kept():\n    assert flatten(["ab", ["cd"]]) == ["ab", "cd"]\n\n\ndef test_empty_nested():\n    assert flatten([[], [[]]]) == []\n\n\ndef test_flat():\n    assert flatten([1, 2]) == [1, 2]\n',
    ),
    dict(
        id="repo-10-moving-average", mod="series", difficulty="medium",
        symptom="`moving_average([1, 2, 3, 4], 2)` returns [1.5, 2.5] instead of [1.5, 2.5, 3.5].",
        spec="Simple moving average with the given window: one value per full window (len(values) - window + 1 values). window < 1 or larger than the data raises ValueError.",
        broken='def moving_average(values, window):\n    if window < 1 or window > len(values):\n        raise ValueError("window")\n    return [sum(values[i : i + window]) / window for i in range(len(values) - window)]\n',
        fixed='def moving_average(values, window):\n    if window < 1 or window > len(values):\n        raise ValueError("window")\n    return [sum(values[i : i + window]) / window for i in range(len(values) - window + 1)]\n',
        visible='import pytest\nfrom lib.series import moving_average\n\n\ndef test_bad_window():\n    with pytest.raises(ValueError):\n        moving_average([1], 2)\n\n\ndef test_window_zero():\n    with pytest.raises(ValueError):\n        moving_average([1], 0)\n',
        hidden='import pytest\nfrom lib.series import moving_average\n\n\ndef test_basic():\n    assert moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]\n\n\ndef test_full_window():\n    assert moving_average([2, 4, 6], 3) == [4]\n\n\ndef test_window_one():\n    assert moving_average([5, 6], 1) == [5, 6]\n\n\ndef test_bad_window():\n    with pytest.raises(ValueError):\n        moving_average([1, 2], 3)\n\n\ndef test_zero_window():\n    with pytest.raises(ValueError):\n        moving_average([1, 2], 0)\n',
    ),
]

# JavaScript greenfield tasks: (id, file, signature text, spec, reference, hidden jest tests)
JS_TASKS = [
    dict(
        id="js-01-clamp", file="clamp", difficulty="easy",
        spec="Export `clamp(value, min, max)` returning value limited to [min, max]. If min > max throw a RangeError.",
        ref="exports.clamp = (v, min, max) => {\n  if (min > max) throw new RangeError('min > max');\n  return Math.min(Math.max(v, min), max);\n};\n",
        test="const { clamp } = require('../src/clamp');\ntest('inside', () => expect(clamp(5, 0, 10)).toBe(5));\ntest('below', () => expect(clamp(-1, 0, 10)).toBe(0));\ntest('above', () => expect(clamp(11, 0, 10)).toBe(10));\ntest('edges', () => { expect(clamp(0, 0, 10)).toBe(0); expect(clamp(10, 0, 10)).toBe(10); });\ntest('bad range', () => expect(() => clamp(1, 5, 1)).toThrow(RangeError));\n",
    ),
    dict(
        id="js-02-capitalize", file="capitalize", difficulty="easy",
        spec="Export `capitalizeWords(text)`: uppercase the first letter of every space-separated word, lowercase the rest, keep single spacing between words, trim the ends. Non-string input throws TypeError.",
        ref="exports.capitalizeWords = (text) => {\n  if (typeof text !== 'string') throw new TypeError('string expected');\n  return text.trim().split(/\\s+/).filter(Boolean)\n    .map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase()).join(' ');\n};\n",
        test="const { capitalizeWords } = require('../src/capitalize');\ntest('basic', () => expect(capitalizeWords('hello world')).toBe('Hello World'));\ntest('mixed case', () => expect(capitalizeWords('hELLO wORLD')).toBe('Hello World'));\ntest('extra spaces', () => expect(capitalizeWords('  a   b ')).toBe('A B'));\ntest('empty', () => expect(capitalizeWords('')).toBe(''));\ntest('type', () => expect(() => capitalizeWords(5)).toThrow(TypeError));\n",
    ),
    dict(
        id="js-03-chunk", file="chunk", difficulty="easy",
        spec="Export `chunk(array, size)` splitting an array into consecutive chunks of at most `size` (last may be shorter). size < 1 or non-integer throws RangeError. Does not mutate the input.",
        ref="exports.chunk = (arr, size) => {\n  if (!Number.isInteger(size) || size < 1) throw new RangeError('bad size');\n  const out = [];\n  for (let i = 0; i < arr.length; i += size) out.push(arr.slice(i, i + size));\n  return out;\n};\n",
        test="const { chunk } = require('../src/chunk');\ntest('remainder', () => expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]));\ntest('exact', () => expect(chunk([1, 2, 3, 4], 2)).toEqual([[1, 2], [3, 4]]));\ntest('empty', () => expect(chunk([], 3)).toEqual([]));\ntest('bad size', () => { expect(() => chunk([1], 0)).toThrow(RangeError); expect(() => chunk([1], 1.5)).toThrow(RangeError); });\ntest('no mutation', () => { const a = [1, 2, 3]; chunk(a, 2); expect(a).toEqual([1, 2, 3]); });\n",
    ),
    dict(
        id="js-04-uniq", file="uniq", difficulty="easy",
        spec="Export `uniq(array)` returning the distinct values keeping first occurrences in order. Uses SameValueZero (so NaN is deduplicated). Does not mutate the input.",
        ref="exports.uniq = (arr) => [...new Set(arr)];\n",
        test="const { uniq } = require('../src/uniq');\ntest('numbers', () => expect(uniq([1, 2, 1, 3, 2])).toEqual([1, 2, 3]));\ntest('order', () => expect(uniq(['b', 'a', 'b'])).toEqual(['b', 'a']));\ntest('nan', () => expect(uniq([NaN, NaN, 1])).toEqual([NaN, 1]));\ntest('types', () => expect(uniq([1, '1'])).toEqual([1, '1']));\ntest('empty', () => expect(uniq([])).toEqual([]));\n",
    ),
    dict(
        id="js-05-group-by", file="groupBy", difficulty="medium",
        spec="Export `groupBy(array, keyFn)` returning an object mapping each key (keyFn(item), converted to string) to the array of items in input order. keyFn must be a function, else TypeError.",
        ref="exports.groupBy = (arr, fn) => {\n  if (typeof fn !== 'function') throw new TypeError('keyFn must be a function');\n  const out = {};\n  for (const item of arr) (out[String(fn(item))] ||= []).push(item);\n  return out;\n};\n",
        test="const { groupBy } = require('../src/groupBy');\ntest('by length', () => expect(groupBy(['a', 'bb', 'c'], (s) => s.length)).toEqual({ 1: ['a', 'c'], 2: ['bb'] }));\ntest('order kept', () => expect(groupBy([3, 1, 2, 4], (n) => n % 2)).toEqual({ 1: [3, 1], 0: [2, 4] }));\ntest('empty', () => expect(groupBy([], (x) => x)).toEqual({}));\ntest('objects', () => expect(groupBy([{ t: 'x', v: 1 }, { t: 'x', v: 2 }], (o) => o.t).x).toHaveLength(2));\ntest('type', () => expect(() => groupBy([1], 'nope')).toThrow(TypeError));\n",
    ),
    dict(
        id="js-06-roman", file="roman", difficulty="medium",
        spec="Export `romanToInt(text)` converting a valid roman numeral (I V X L C D M, subtractive pairs IV IX XL XC CD CM) to a number. Empty input or unknown characters throw an Error.",
        ref="const V = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };\nexports.romanToInt = (s) => {\n  if (typeof s !== 'string' || !s || [...s].some((c) => !(c in V))) throw new Error('invalid');\n  let total = 0;\n  for (let i = 0; i < s.length; i++) total += V[s[i]] < (V[s[i + 1]] || 0) ? -V[s[i]] : V[s[i]];\n  return total;\n};\n",
        test="const { romanToInt } = require('../src/roman');\ntest('simple', () => expect(romanToInt('VIII')).toBe(8));\ntest('subtractive', () => { expect(romanToInt('IV')).toBe(4); expect(romanToInt('IX')).toBe(9); });\ntest('long', () => expect(romanToInt('MCMXCIV')).toBe(1994));\ntest('invalid', () => { expect(() => romanToInt('')).toThrow(); expect(() => romanToInt('ABC')).toThrow(); });\ntest('xl', () => expect(romanToInt('XLII')).toBe(42));\n",
    ),
    dict(
        id="js-07-format-bytes", file="formatBytes", difficulty="medium",
        spec="Export `formatBytes(n)` returning a human string with 1024-based units B, KB, MB, GB, TB: integer bytes below 1024 as '<n> B', otherwise one decimal ('1.5 KB'). Negative or non-finite input throws RangeError.",
        ref="exports.formatBytes = (n) => {\n  if (!Number.isFinite(n) || n < 0) throw new RangeError('bad size');\n  if (n < 1024) return `${n} B`;\n  const units = ['KB', 'MB', 'GB', 'TB'];\n  let v = n / 1024, i = 0;\n  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }\n  return `${v.toFixed(1)} ${units[i]}`;\n};\n",
        test="const { formatBytes } = require('../src/formatBytes');\ntest('bytes', () => { expect(formatBytes(0)).toBe('0 B'); expect(formatBytes(1023)).toBe('1023 B'); });\ntest('kb', () => { expect(formatBytes(1024)).toBe('1.0 KB'); expect(formatBytes(1536)).toBe('1.5 KB'); });\ntest('mb', () => expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB'));\ntest('tb cap', () => expect(formatBytes(2 * 1024 ** 4)).toBe('2.0 TB'));\ntest('invalid', () => { expect(() => formatBytes(-1)).toThrow(RangeError); expect(() => formatBytes(NaN)).toThrow(RangeError); });\n",
    ),
    dict(
        id="js-08-parse-query", file="parseQuery", difficulty="medium",
        spec="Export `parseQuery(qs)` parsing a query string (optional leading '?') into an object: percent-decoded keys and values, '+' means space, a repeated key becomes an array in order, a key without '=' has value ''. Empty input gives {}.",
        ref="exports.parseQuery = (qs) => {\n  const s = qs.startsWith('?') ? qs.slice(1) : qs;\n  const out = {};\n  if (!s) return out;\n  for (const part of s.split('&')) {\n    if (!part) continue;\n    const [k, v = ''] = part.split('=');\n    const key = decodeURIComponent(k.replace(/\\+/g, ' '));\n    const val = decodeURIComponent(v.replace(/\\+/g, ' '));\n    if (key in out) out[key] = [].concat(out[key], val);\n    else out[key] = val;\n  }\n  return out;\n};\n",
        test="const { parseQuery } = require('../src/parseQuery');\ntest('basic', () => expect(parseQuery('a=1&b=2')).toEqual({ a: '1', b: '2' }));\ntest('leading ?', () => expect(parseQuery('?a=1')).toEqual({ a: '1' }));\ntest('decode', () => expect(parseQuery('q=hello+world&x=%C3%A9')).toEqual({ q: 'hello world', x: 'é' }));\ntest('repeated', () => expect(parseQuery('t=a&t=b&t=c')).toEqual({ t: ['a', 'b', 'c'] }));\ntest('no value', () => expect(parseQuery('flag')).toEqual({ flag: '' }));\ntest('empty', () => { expect(parseQuery('')).toEqual({}); expect(parseQuery('?')).toEqual({}); });\n",
    ),
    dict(
        id="js-09-camel-to-snake", file="caseConvert", difficulty="easy",
        spec="Export `camelToSnake(text)` and `snakeToCamel(text)`. camelToSnake('myHTTPServer2') -> 'my_http_server2'; snakeToCamel('my_http_server') -> 'myHttpServer'. Leading/trailing/double underscores are dropped when converting to camel; already-converted input is returned unchanged.",
        ref="exports.camelToSnake = (s) => s\n  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')\n  .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')\n  .toLowerCase();\nexports.snakeToCamel = (s) => s\n  .split('_').filter(Boolean)\n  .map((w, i) => (i ? w[0].toUpperCase() + w.slice(1) : w))\n  .join('');\n",
        test="const { camelToSnake, snakeToCamel } = require('../src/caseConvert');\ntest('simple', () => expect(camelToSnake('myValue')).toBe('my_value'));\ntest('acronym', () => expect(camelToSnake('myHTTPServer2')).toBe('my_http_server2'));\ntest('unchanged', () => expect(camelToSnake('already_snake')).toBe('already_snake'));\ntest('to camel', () => expect(snakeToCamel('my_http_server')).toBe('myHttpServer'));\ntest('odd underscores', () => expect(snakeToCamel('__a__b_')).toBe('aB'));\ntest('unchanged camel', () => expect(snakeToCamel('plain')).toBe('plain'));\n",
    ),
    dict(
        id="js-10-deep-equal", file="deepEqual", difficulty="hard",
        spec="Export `deepEqual(a, b)`: structural equality for primitives (NaN equals NaN), arrays, plain objects (key order irrelevant) and Dates (by time). Different types are never equal; arrays never equal objects; cyclic structures are not required.",
        ref="exports.deepEqual = function deepEqual(a, b) {\n  if (Object.is(a, b) || a === b) return true;\n  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null) return false;\n  if (a instanceof Date || b instanceof Date) {\n    return a instanceof Date && b instanceof Date && a.getTime() === b.getTime();\n  }\n  if (Array.isArray(a) !== Array.isArray(b)) return false;\n  const ka = Object.keys(a), kb = Object.keys(b);\n  if (ka.length !== kb.length) return false;\n  return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));\n};\n",
        test="const { deepEqual } = require('../src/deepEqual');\ntest('primitives', () => { expect(deepEqual(1, 1)).toBe(true); expect(deepEqual(1, '1')).toBe(false); expect(deepEqual(NaN, NaN)).toBe(true); });\ntest('arrays', () => { expect(deepEqual([1, [2]], [1, [2]])).toBe(true); expect(deepEqual([1, 2], [2, 1])).toBe(false); });\ntest('objects', () => { expect(deepEqual({ a: 1, b: { c: 2 } }, { b: { c: 2 }, a: 1 })).toBe(true); expect(deepEqual({ a: 1 }, { a: 1, b: undefined })).toBe(false); });\ntest('array vs object', () => expect(deepEqual([], {})).toBe(false));\ntest('dates', () => { expect(deepEqual(new Date(5), new Date(5))).toBe(true); expect(deepEqual(new Date(5), new Date(6))).toBe(false); });\ntest('null', () => { expect(deepEqual(null, null)).toBe(true); expect(deepEqual(null, {})).toBe(false); });\n",
    ),
]
