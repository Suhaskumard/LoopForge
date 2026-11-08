const V = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 };
exports.romanToInt = (s) => {
  if (typeof s !== 'string' || !s || [...s].some((c) => !(c in V))) throw new Error('invalid');
  let total = 0;
  for (let i = 0; i < s.length; i++) total += V[s[i]] < (V[s[i + 1]] || 0) ? -V[s[i]] : V[s[i]];
  return total;
};
