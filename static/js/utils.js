/* Utilitários compartilhados de Curadoria/Frontend. */
(function (globalScope) {
  'use strict';

  function _toNumberLike(raw) {
    if (raw === null || raw === undefined) return null;
    if (typeof raw === 'number') return Number.isFinite(raw) ? raw : null;
    var s = String(raw).trim();
    if (!s) return null;
    s = s.replace(/[^\d,.-]/g, '');
    if (!s) return null;
    if (s.indexOf(',') >= 0) {
      s = s.replace(/\./g, '').replace(',', '.');
    }
    var n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  function parsePrecoBooking(elOrRaw) {
    if (elOrRaw === null || elOrRaw === undefined) return null;
    var raw = elOrRaw;
    if (typeof elOrRaw === 'object') {
      if (typeof elOrRaw.getAttribute === 'function') {
        raw = elOrRaw.getAttribute('data-preco-booking');
      } else if (elOrRaw.dataset && Object.prototype.hasOwnProperty.call(elOrRaw.dataset, 'precoBooking')) {
        raw = elOrRaw.dataset.precoBooking;
      } else if (Object.prototype.hasOwnProperty.call(elOrRaw, 'preco_booking')) {
        raw = elOrRaw.preco_booking;
      }
    }
    return _toNumberLike(raw);
  }

  function safeRound(value) {
    var n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Number(n.toFixed(2));
  }

  function formatMoneyBR(value) {
    var n = Number(value);
    if (!Number.isFinite(n) || n < 0) n = 0;
    return n.toLocaleString('pt-BR', {
      style: 'currency',
      currency: 'BRL',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  var api = {
    parsePrecoBooking: parsePrecoBooking,
    formatMoneyBR: formatMoneyBR,
    safeRound: safeRound
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  if (globalScope) {
    globalScope.CuradoriaUtils = api;
  }
})(typeof window !== 'undefined' ? window : globalThis);
