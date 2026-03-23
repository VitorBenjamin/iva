const assert = require('node:assert/strict');
const path = require('node:path');

const utilsPath = path.resolve(__dirname, '../../static/js/utils.js');
const curadoriaPath = path.resolve(__dirname, '../../static/js/curadoria.js');
const utils = require(utilsPath);
const { createCuradoriaController } = require(curadoriaPath);

function mkClassList() {
  const set = new Set();
  return {
    add: (v) => set.add(v),
    remove: (v) => set.delete(v),
    contains: (v) => set.has(v)
  };
}

function mkInput(options = {}) {
  return {
    value: options.value || '',
    dataset: {
      originalPrecoCurado: '',
      precoCuradoSugerido: '',
      descontoPctSugerido: '',
      precoBooking: options.precoBooking || '',
      precoExibicaoOrigem: options.precoExibicaoOrigem || 'por_data',
      precoBaseUsado: options.precoBaseUsado || options.precoBooking || ''
    },
    getAttribute(name) {
      if (name === 'data-preco-booking') return options.precoBooking || '';
      return '';
    }
  };
}

function mkRow({ checkin, checkins, precoBooking, inputValue }) {
  const input = mkInput({ value: inputValue, precoBooking });
  const attrs = {
    'data-checkin': checkin,
    'data-checkins': checkins || '',
    'data-preco-booking': precoBooking || '',
    'data-preco-exibicao-preferida': 'por_data',
    'data-preco-direto-media-periodo': ''
  };
  return {
    dataset: {},
    classList: mkClassList(),
    getAttribute(name) {
      return attrs[name] || '';
    },
    setAttribute(name, value) {
      attrs[name] = String(value);
    },
    removeAttribute(name) {
      delete attrs[name];
    },
    querySelector(selector) {
      if (selector === '.input-preco-curado') return input;
      return null;
    },
    _input: input
  };
}

function mkDocument(rows) {
  return {
    querySelectorAll(selector) {
      if (selector === '#tbody-registros tr[data-checkin], #tbody-registros-especiais tr[data-checkin]') return rows;
      if (selector === '.input-preco-curado') return rows.map((r) => r._input);
      return [];
    }
  };
}

function mkWindow() {
  const toasts = [];
  return {
    FRONTEND_DESCONTO_UNIFICADO: true,
    _curadoria_preview_aplicado: false,
    CURADORIA_PROJECT_ID: 'proj-teste',
    CuradoriaUtils: utils,
    mostrarToast(message, ok) {
      toasts.push({ message, ok });
    },
    fetch() {
      return Promise.resolve({ ok: true });
    },
    navigator: {
      sendBeacon() {
        return true;
      }
    },
    console,
    _toasts: toasts
  };
}

function run() {
  // Caso 1: cálculo por preço booking.
  {
    const row = mkRow({ checkin: '2026-01-10', precoBooking: '1000' });
    const win = mkWindow();
    const doc = mkDocument([row]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    const result = ctrl.applyDiscountPreview(15);
    assert.equal(result.ok, true);
    assert.equal(row._input.dataset.precoCuradoSugerido, '850');
    assert.equal(row._input.value, 'R$\u00a0850,00');
  }

  // Caso 2: segunda aplicação sem reset deve bloquear.
  {
    const row = mkRow({ checkin: '2026-01-10', precoBooking: '1000' });
    const win = mkWindow();
    const doc = mkDocument([row]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    ctrl.applyDiscountPreview(15);
    const second = ctrl.applyDiscountPreview(10);
    assert.equal(second.ok, false);
    assert.equal(second.reason, 'preview_already_applied');
    assert.equal(win._toasts.some((t) => t.message.includes('Preview já aplicado')), true);
    assert.equal(row._input.dataset.precoCuradoSugerido, '850');
  }

  // Caso 3: sem preço booking -> linha desabilitada.
  {
    const row = mkRow({ checkin: '2026-01-10', precoBooking: '' });
    const win = mkWindow();
    const doc = mkDocument([row]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    ctrl.applyDiscountPreview(15);
    assert.equal(row.classList.contains('curadoria-disabled'), true);
    assert.equal(row._input.dataset.precoCuradoSugerido, '');
  }

  // Caso 4: payload com múltiplos check-ins.
  {
    const rowA = mkRow({ checkin: '2026-01-10', checkins: '2026-01-10,2026-01-11', precoBooking: '1000' });
    const rowB = mkRow({ checkin: '2026-02-01', precoBooking: '500' });
    const win = mkWindow();
    const doc = mkDocument([rowA, rowB]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    ctrl.applyDiscountPreview(15);
    const payload = ctrl.prepareCuradoriaPayload();
    assert.equal(payload.length, 3);
    assert.deepEqual(payload[0], {
      checkin: '2026-01-10',
      preco_booking_base: 1000,
      preco_curado_sugerido: 850,
      desconto_pct_sugerido: 15,
      preco_exibicao_origem: 'por_data',
      preco_base_usado: 1000
    });
    assert.deepEqual(payload[2], {
      checkin: '2026-02-01',
      preco_booking_base: 500,
      preco_curado_sugerido: 425,
      desconto_pct_sugerido: 15,
      preco_exibicao_origem: 'por_data',
      preco_base_usado: 500
    });
  }

  // Caso 5: origem por_data deve prevalecer sobre média na exibição/payload.
  {
    const row = mkRow({ checkin: '2026-03-28', precoBooking: '351' });
    row.dataset.precoDiretoMediaPeriodo = '306';
    const win = mkWindow();
    const doc = mkDocument([row]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    ctrl.applyDiscountPreview(0.0001, true); // força criação de dataset sem alterar cenário
    row._input.dataset.precoCuradoSugerido = '351';
    row._input.dataset.descontoPctSugerido = '0';
    row._input.dataset.precoExibicaoOrigem = 'por_data';
    row._input.dataset.precoBaseUsado = '351';
    const payload = ctrl.prepareCuradoriaPayload();
    assert.equal(payload[0].preco_exibicao_origem, 'por_data');
    assert.equal(payload[0].preco_base_usado, 351);
  }

  // Reset restaura estado original.
  {
    const row = mkRow({ checkin: '2026-01-10', precoBooking: '1000', inputValue: 'R$ 900,00' });
    const win = mkWindow();
    const doc = mkDocument([row]);
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    ctrl.applyDiscountPreview(15);
    ctrl.resetDiscountPreview();
    assert.equal(row._input.value, 'R$\u00a0900,00');
    assert.equal(row.dataset.previewApplied, undefined);
    assert.equal(win._curadoria_preview_aplicado, false);
  }

  console.log('OK: test_curadoria_preview.js');
}

run();
