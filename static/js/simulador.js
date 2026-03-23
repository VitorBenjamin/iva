/* Utilitarios do simulador (UI/UX) */
(function () {
  'use strict';

  function parseMoedaBR(valor) {
    if (!valor) return 0;
    var v = String(valor).replace(/\D/g, '');
    return v ? parseFloat(v) / 100 : 0;
  }

  window.SimuladorUtils = window.SimuladorUtils || {};
  window.SimuladorUtils.parseMoedaBR = parseMoedaBR;
})();

