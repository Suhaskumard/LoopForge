const { romanToInt } = require('../src/roman');
test('simple', () => expect(romanToInt('VIII')).toBe(8));
test('subtractive', () => { expect(romanToInt('IV')).toBe(4); expect(romanToInt('IX')).toBe(9); });
test('long', () => expect(romanToInt('MCMXCIV')).toBe(1994));
test('invalid', () => { expect(() => romanToInt('')).toThrow(); expect(() => romanToInt('ABC')).toThrow(); });
test('xl', () => expect(romanToInt('XLII')).toBe(42));
