const { parseQuery } = require('../src/parseQuery');
test('basic', () => expect(parseQuery('a=1&b=2')).toEqual({ a: '1', b: '2' }));
test('leading ?', () => expect(parseQuery('?a=1')).toEqual({ a: '1' }));
test('decode', () => expect(parseQuery('q=hello+world&x=%C3%A9')).toEqual({ q: 'hello world', x: 'é' }));
test('repeated', () => expect(parseQuery('t=a&t=b&t=c')).toEqual({ t: ['a', 'b', 'c'] }));
test('no value', () => expect(parseQuery('flag')).toEqual({ flag: '' }));
test('empty', () => { expect(parseQuery('')).toEqual({}); expect(parseQuery('?')).toEqual({}); });
