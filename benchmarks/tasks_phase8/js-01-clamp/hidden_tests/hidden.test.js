const { clamp } = require('../src/clamp');
test('inside', () => expect(clamp(5, 0, 10)).toBe(5));
test('below', () => expect(clamp(-1, 0, 10)).toBe(0));
test('above', () => expect(clamp(11, 0, 10)).toBe(10));
test('edges', () => { expect(clamp(0, 0, 10)).toBe(0); expect(clamp(10, 0, 10)).toBe(10); });
test('bad range', () => expect(() => clamp(1, 5, 1)).toThrow(RangeError));
