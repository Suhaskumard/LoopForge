exports.groupBy = (arr, fn) => {
  if (typeof fn !== 'function') throw new TypeError('keyFn must be a function');
  const out = {};
  for (const item of arr) (out[String(fn(item))] ||= []).push(item);
  return out;
};
