const { formatBytes } = require('../src/formatBytes');
test('bytes', () => { expect(formatBytes(0)).toBe('0 B'); expect(formatBytes(1023)).toBe('1023 B'); });
test('kb', () => { expect(formatBytes(1024)).toBe('1.0 KB'); expect(formatBytes(1536)).toBe('1.5 KB'); });
test('mb', () => expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB'));
test('tb cap', () => expect(formatBytes(2 * 1024 ** 4)).toBe('2.0 TB'));
test('invalid', () => { expect(() => formatBytes(-1)).toThrow(RangeError); expect(() => formatBytes(NaN)).toThrow(RangeError); });
