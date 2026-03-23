const assert = require('node:assert/strict');

function roundTo(value, decimals = 4) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Number(n.toFixed(decimals));
}

function normalizePercent(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return roundTo(n > 1 ? n / 100 : n, 4);
}

function run() {
  assert.equal(roundTo(14.00000000000002, 4), 14);
  assert.equal(normalizePercent(14), 0.14);
  assert.equal(normalizePercent(0.071234), 0.0712);
  assert.equal(roundTo(1234.567, 2), 1234.57);
  console.log('OK: test_financeiro_utils.js');
}

run();
