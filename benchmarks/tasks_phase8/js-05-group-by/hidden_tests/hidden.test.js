const { groupBy } = require('../src/groupBy');
test('by length', () => expect(groupBy(['a', 'bb', 'c'], (s) => s.length)).toEqual({ 1: ['a', 'c'], 2: ['bb'] }));
test('order kept', () => expect(groupBy([3, 1, 2, 4], (n) => n % 2)).toEqual({ 1: [3, 1], 0: [2, 4] }));
test('empty', () => expect(groupBy([], (x) => x)).toEqual({}));
test('objects', () => expect(groupBy([{ t: 'x', v: 1 }, { t: 'x', v: 2 }], (o) => o.t).x).toHaveLength(2));
test('type', () => expect(() => groupBy([1], 'nope')).toThrow(TypeError));
