const { camelToSnake, snakeToCamel } = require('../src/caseConvert');
test('simple', () => expect(camelToSnake('myValue')).toBe('my_value'));
test('acronym', () => expect(camelToSnake('myHTTPServer2')).toBe('my_http_server2'));
test('unchanged', () => expect(camelToSnake('already_snake')).toBe('already_snake'));
test('to camel', () => expect(snakeToCamel('my_http_server')).toBe('myHttpServer'));
test('odd underscores', () => expect(snakeToCamel('__a__b_')).toBe('aB'));
test('unchanged camel', () => expect(snakeToCamel('plain')).toBe('plain'));
