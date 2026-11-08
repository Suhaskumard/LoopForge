exports.parseQuery = (qs) => {
  const s = qs.startsWith('?') ? qs.slice(1) : qs;
  const out = {};
  if (!s) return out;
  for (const part of s.split('&')) {
    if (!part) continue;
    const [k, v = ''] = part.split('=');
    const key = decodeURIComponent(k.replace(/\+/g, ' '));
    const val = decodeURIComponent(v.replace(/\+/g, ' '));
    if (key in out) out[key] = [].concat(out[key], val);
    else out[key] = val;
  }
  return out;
};
