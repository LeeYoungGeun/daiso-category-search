const { search } = require('./search');

describe('search', () => {
  test('should return empty array when query is empty', () => {
    const result = search('');
    expect(result).toEqual([]);
  });
});
