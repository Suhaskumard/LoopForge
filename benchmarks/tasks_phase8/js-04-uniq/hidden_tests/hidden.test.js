const { uniq } = require('../src/uniq');
test('numbers', () => expect(uniq([1, 2, 1, 3, 2])).toEqual([1, 2, 3]));
test('order', () => expect(uniq(['b', 'a', 'b'])).toEqual(['b', 'a']));
test('nan', () => expect(uniq([NaN, NaN, 1])).toEqual([NaN, 1]));
test('types', () => expect(uniq([1, '1'])).toEqual([1, '1']));
test('empty', () => expect(uniq([])).toEqual([]));
