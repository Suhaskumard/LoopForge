const { deepEqual } = require('../src/deepEqual');
test('primitives', () => { expect(deepEqual(1, 1)).toBe(true); expect(deepEqual(1, '1')).toBe(false); expect(deepEqual(NaN, NaN)).toBe(true); });
test('arrays', () => { expect(deepEqual([1, [2]], [1, [2]])).toBe(true); expect(deepEqual([1, 2], [2, 1])).toBe(false); });
test('objects', () => { expect(deepEqual({ a: 1, b: { c: 2 } }, { b: { c: 2 }, a: 1 })).toBe(true); expect(deepEqual({ a: 1 }, { a: 1, b: undefined })).toBe(false); });
test('array vs object', () => expect(deepEqual([], {})).toBe(false));
test('dates', () => { expect(deepEqual(new Date(5), new Date(5))).toBe(true); expect(deepEqual(new Date(5), new Date(6))).toBe(false); });
test('null', () => { expect(deepEqual(null, null)).toBe(true); expect(deepEqual(null, {})).toBe(false); });
