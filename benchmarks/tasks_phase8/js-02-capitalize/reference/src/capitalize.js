exports.capitalizeWords = (text) => {
  if (typeof text !== 'string') throw new TypeError('string expected');
  return text.trim().split(/\s+/).filter(Boolean)
    .map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase()).join(' ');
};
