const { chunk } = require('../src/chunk');
test('remainder', () => expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]));
test('exact', () => expect(chunk([1, 2, 3, 4], 2)).toEqual([[1, 2], [3, 4]]));
test('empty', () => expect(chunk([], 3)).toEqual([]));
test('bad size', () => { expect(() => chunk([1], 0)).toThrow(RangeError); expect(() => chunk([1], 1.5)).toThrow(RangeError); });
test('no mutation', () => { const a = [1, 2, 3]; chunk(a, 2); expect(a).toEqual([1, 2, 3]); });
