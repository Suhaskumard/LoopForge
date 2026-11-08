exports.camelToSnake = (s) => s
  .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
  .replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2')
  .toLowerCase();
exports.snakeToCamel = (s) => s
  .split('_').filter(Boolean)
  .map((w, i) => (i ? w[0].toUpperCase() + w.slice(1) : w))
  .join('');
