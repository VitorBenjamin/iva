const assert = require('node:assert/strict');
const path = require('node:path');

const utilsPath = path.resolve(__dirname, '../../static/js/utils.js');
const { parsePrecoBooking, formatMoneyBR, safeRound } = require(utilsPath);

function run() {
  // parsePrecoBooking: números e strings em formatos comuns.
  assert.equal(parsePrecoBooking('1000'), 1000);
  assert.equal(parsePrecoBooking('1000.5'), 1000.5);
  assert.equal(parsePrecoBooking('R$ 1.234,56'), 1234.56);
  assert.equal(parsePrecoBooking({ preco_booking: 'R$ 999,90' }), 999.9);
  assert.equal(parsePrecoBooking({ dataset: { precoBooking: '1500,00' } }), 1500);
  assert.equal(parsePrecoBooking(''), null);
  assert.equal(parsePrecoBooking('abc'), null);

  // safeRound: duas casas decimais estáveis.
  assert.equal(safeRound(850), 850);
  assert.equal(safeRound(850.005), 850);
  assert.equal(safeRound(850.006), 850.01);
  assert.equal(safeRound('x'), 0);

  // formatMoneyBR: formato monetário pt-BR.
  assert.equal(formatMoneyBR(850), 'R$\u00a0850,00');
  assert.equal(formatMoneyBR(850.1), 'R$\u00a0850,10');
  assert.equal(formatMoneyBR(-1), 'R$\u00a00,00');

  console.log('OK: test_curadoria_utils.js');
}

run();
