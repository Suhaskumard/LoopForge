exports.clamp = (v, min, max) => {
  if (min > max) throw new RangeError('min > max');
  return Math.min(Math.max(v, min), max);
};
