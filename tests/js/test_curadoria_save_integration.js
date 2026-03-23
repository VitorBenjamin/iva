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

function mkElement() {
  return {
    value: '',
    textContent: '',
    dataset: {},
    classList: mkClassList(),
    attributes: {},
    children: [],
    disabled: false,
    innerHTML: '',
    listeners: {},
    addEventListener(name, fn) {
      this.listeners[name] = this.listeners[name] || [];
      this.listeners[name].push(fn);
    },
    dispatchEvent(evt) {
      const list = this.listeners[evt.type] || [];
      list.forEach((fn) => fn(evt));
    },
    setAttribute(name, value) {
      this.attributes[name] = String(value);
    },
    getAttribute(name) {
      return this.attributes[name] || '';
    },
    removeAttribute(name) {
      delete this.attributes[name];
    },
    appendChild(el) {
      this.children.push(el);
    },
    querySelector() {
      return null;
    }
  };
}

function mkRow(checkin, suggested, pct) {
  const input = mkElement();
  const auditLabel = mkElement();
  const auditBtn = mkElement();
  auditBtn.querySelector = (selector) => (selector === '.iva-audit-label' ? auditLabel : null);
  const auditCell = mkElement();
  auditCell.querySelector = (selector) => {
    if (selector === '.iva-audit-btn') return auditBtn;
    if (selector === '.iva-audit-label') return auditLabel;
    return null;
  };
  input.dataset.precoCuradoSugerido = String(suggested);
  input.dataset.descontoPctSugerido = String(pct);
  input.dataset.precoExibicaoOrigem = 'por_data';
  input.dataset.precoBaseUsado = '1000';
  const row = mkElement();
  row.attributes['data-checkin'] = checkin;
  row.attributes['data-checkins'] = checkin;
  row.attributes['data-preco-booking'] = '1000';
  row.attributes['data-preco-exibicao-preferida'] = 'por_data';
  row.querySelector = (selector) => {
    if (selector === '.input-preco-curado') return input;
    if (selector === '.iva-curadoria-audit-col') return auditCell;
    return null;
  };
  row._input = input;
  row._auditCell = auditCell;
  row._auditBtn = auditBtn;
  row._auditLabel = auditLabel;
  return row;
}

function mkDocument(rows) {
  const btnSave = mkElement();
  btnSave.textContent = 'Salvar Ajustes';
  const modalTbody = mkElement();
  const modal = mkElement();
  const ivaToastContainer = mkElement();
  const dynamicElements = {};
  const listeners = {};
  ivaToastContainer.insertAdjacentHTML = (pos, html) => {
    ivaToastContainer.innerHTML += html;
    const m = html.match(/id="(btn-ver-correcoes-[^"]+)"/);
    if (m) dynamicElements[m[1]] = mkElement();
  };
  return {
    querySelectorAll(selector) {
      if (selector === '#tbody-registros tr[data-checkin], #tbody-registros-especiais tr[data-checkin]') return rows;
      if (selector === '.input-preco-curado') return rows.map((r) => r._input);
      return [];
    },
    getElementById(id) {
      if (id === 'btn-salvar-ajustes') return btnSave;
      if (id === 'tbody-correcoes-curadoria') return modalTbody;
      if (id === 'modal-correcoes-curadoria') return modal;
      if (id === 'iva-toast-container') return ivaToastContainer;
      if (dynamicElements[id]) return dynamicElements[id];
      return null;
    },
    createElement() {
      return mkElement();
    },
    addEventListener(name, fn) {
      listeners[name] = listeners[name] || [];
      listeners[name].push(fn);
    },
    _btnSave: btnSave,
    _modalTbody: modalTbody,
    _ivaToastContainer: ivaToastContainer,
    _dynamicElements: dynamicElements
  };
}

function mkWindow(fetchImpl) {
  const toasts = [];
  const logs = [];
  return {
    FRONTEND_DESCONTO_UNIFICADO: true,
    CURADORIA_PROJECT_ID: 'proj-integration',
    CuradoriaUtils: utils,
    mostrarToast(msg, ok) {
      toasts.push({ msg, ok });
    },
    fetch: fetchImpl,
    navigator: { sendBeacon: () => true },
    setTimeout,
    clearTimeout,
    console,
    bootstrap: { Modal: { getOrCreateInstance: () => ({ show: () => logs.push('modal_show') }) } },
    _toasts: toasts,
    _logs: logs
  };
}

async function run() {
  // Caso 1: sem correção, sem highlight.
  {
    let posted = null;
    const row = mkRow('2026-01-10', 850, 15);
    const doc = mkDocument([row]);
    const win = mkWindow((url, opts) => {
      posted = { url, opts };
      return Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true, data: { registros_salvos: 1, itens_corrigidos: [], itens_invalidos: [] } })
      });
    });
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    row._input.dataset.precoCuradoSugerido = '850';
    row._input.dataset.descontoPctSugerido = '15';
    const result = await ctrl.sendCuradoriaSave();
    assert.equal(result.ok, true);
    const body = JSON.parse(posted.opts.body);
    assert.equal(body.registros[0].preco_exibicao_origem, 'por_data');
    assert.equal(body.registros[0].preco_base_usado, 1000);
    assert.equal(row.classList.contains('curadoria-corrigida'), false);
    assert.equal(doc._btnSave.disabled, false);
    assert.equal(doc._ivaToastContainer.innerHTML.includes('Ver correções'), true);
  }

  // Caso 2: com correção, destaca linha e grava audit attrs.
  {
    const row = mkRow('2026-01-10', 700, 15);
    const doc = mkDocument([row]);
    const win = mkWindow(() => Promise.resolve({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        success: true,
        data: {
          registros_salvos: 1,
          itens_corrigidos: [{ checkin: '2026-01-10', preco_sugerido: 700, preco_backend: 850, desconto_aplicado: '0.15' }],
          itens_invalidos: []
        }
      })
    }));
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    row._input.dataset.precoCuradoSugerido = '700';
    row._input.dataset.descontoPctSugerido = '15';
    const result = await ctrl.sendCuradoriaSave();
    assert.equal(result.ok, true);
    assert.equal(row.classList.contains('curadoria-corrigida'), true);
    assert.equal(row.classList.contains('iva-curadoria-corrigida'), true);
    assert.equal(Boolean(row.dataset.auditUser), true);
    assert.equal(row.dataset.descontoAplicado, '0.15');
    assert.equal(row.dataset.displaySourceAfterSave, 'por_data');
    assert.equal(row._auditLabel.textContent.includes('850') || row._auditLabel.textContent.includes('850'.slice(0, 3)), true);
    // dispara clique no botão de "Ver correções" criado no toast.
    const dynamicIds = Object.keys(doc._dynamicElements);
    assert.equal(dynamicIds.length > 0, true);
    const btn = doc._dynamicElements[dynamicIds[0]];
    const handlers = btn.listeners.click || [];
    assert.equal(handlers.length > 0, true);
    handlers[0]({ type: 'click' });
    assert.equal(win._logs.includes('modal_show'), true);
  }

  // Caso 3: erro de rede reabilita botão e mostra toast.
  {
    const row = mkRow('2026-01-10', 850, 15);
    const doc = mkDocument([row]);
    const win = mkWindow(() => Promise.reject(new Error('network down')));
    const ctrl = createCuradoriaController(win, doc);
    ctrl.initCuradoriaRowsState();
    row._input.dataset.precoCuradoSugerido = '850';
    row._input.dataset.descontoPctSugerido = '15';
    const result = await ctrl.sendCuradoriaSave();
    assert.equal(result.ok, false);
    assert.equal(result.reason, 'network_error');
    assert.equal(doc._btnSave.disabled, false);
    assert.equal(win._toasts.some((t) => t.msg.includes('Erro de rede')), true);
  }

  console.log('OK: test_curadoria_save_integration.js');
}

async function main() {
  try {
    await run();
  } catch (err) {
    console.error(err);
    process.exit(1);
  }
}

main();
