const { capitalizeWords } = require('../src/capitalize');
test('basic', () => expect(capitalizeWords('hello world')).toBe('Hello World'));
test('mixed case', () => expect(capitalizeWords('hELLO wORLD')).toBe('Hello World'));
test('extra spaces', () => expect(capitalizeWords('  a   b ')).toBe('A B'));
test('empty', () => expect(capitalizeWords('')).toBe(''));
test('type', () => expect(() => capitalizeWords(5)).toThrow(TypeError));
