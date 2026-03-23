const assert = require('node:assert/strict');
const path = require('node:path');

const utilsPath = path.resolve(__dirname, '../../static/js/utils.js');
const curadoriaPath = path.resolve(__dirname, '../../static/js/curadoria.js');
const utils = require(utilsPath);
const { createCuradoriaController } = require(curadoriaPath);

function mkElement() {
  return {
    innerHTML: '',
    listeners: {},
    addEventListener(name, fn) {
      this.listeners[name] = this.listeners[name] || [];
      this.listeners[name].push(fn);
    },
    setAttribute() {},
    querySelector() { return null; }
  };
}

function mkDoc() {
  const toastContainer = mkElement();
  const dynamic = {};
  toastContainer.insertAdjacentHTML = (pos, html) => {
    toastContainer.innerHTML += html;
    const match = html.match(/id="(btn-ver-correcoes-[^"]+)"/);
    if (match) {
      dynamic[match[1]] = mkElement();
    }
  };
  return {
    querySelectorAll() { return []; },
    getElementById(id) {
      if (id === 'iva-toast-container') return toastContainer;
      return dynamic[id] || null;
    },
    addEventListener() {},
    createElement() { return mkElement(); },
    _toastContainer: toastContainer,
    _dynamic: dynamic
  };
}

function mkWin() {
  return {
    CURADORIA_PROJECT_ID: 'a11y-proj',
    CuradoriaUtils: utils,
    navigator: { sendBeacon: () => true },
    fetch: () => Promise.resolve({ ok: true }),
    setTimeout,
    clearTimeout,
    bootstrap: { Modal: { getOrCreateInstance: () => ({ show: () => {} }) } },
    console
  };
}

function run() {
  const doc = mkDoc();
  const win = mkWin();
  const ctrl = createCuradoriaController(win, doc);
  ctrl.showSaveSummaryToast({ salvos: 2, corrigidos: 1, itensCorrigidos: [{ checkin: '2026-03-20' }] });
  assert.equal(doc._toastContainer.innerHTML.includes('aria-live="polite"'), true);
  assert.equal(doc._toastContainer.innerHTML.includes('aria-label="Ver correções aplicadas no save"'), true);

  const keys = Object.keys(doc._dynamic);
  assert.equal(keys.length > 0, true);
  const btn = doc._dynamic[keys[0]];
  assert.equal(Array.isArray(btn.listeners.keydown), true);
  assert.equal(Array.isArray(btn.listeners.click), true);
  console.log('OK: test_curadoria_a11y.js');
}

run();
