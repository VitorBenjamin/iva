/* Fluxo de preview de desconto da Curadoria (ATO 3.3.2). */
(function (globalScope) {
  'use strict';

  function createCuradoriaController(win, doc) {
    var CuradoriaUtils = win.CuradoriaUtils || {};
    var parsePrecoBooking = CuradoriaUtils.parsePrecoBooking || function () { return null; };
    var formatMoneyBR = CuradoriaUtils.formatMoneyBR || function (v) { return String(v); };
    var safeRound = CuradoriaUtils.safeRound || function (v) { return Number(v); };

    function getRows() {
      return Array.prototype.slice.call(doc.querySelectorAll('#tbody-registros tr[data-checkin], #tbody-registros-especiais tr[data-checkin]'));
    }

    function getRowByCheckin(checkin) {
      var found = null;
      getRows().some(function (row) {
        var checkinsAttr = row.getAttribute('data-checkins') || row.getAttribute('data-checkin') || '';
        var checkins = checkinsAttr.split(',').map(function (c) { return c.trim(); }).filter(Boolean);
        if (checkins.indexOf(checkin) >= 0) {
          found = row;
          return true;
        }
        return false;
      });
      return found;
    }

    function parseCurrencyInputValue(inputEl) {
      if (!inputEl || !inputEl.value) return null;
      var cleaned = String(inputEl.value).replace(/\D/g, '');
      if (!cleaned) return null;
      var parsed = Number.parseFloat(cleaned) / 100;
      return Number.isFinite(parsed) ? parsed : null;
    }

    function showPreviewToast(message, variant) {
      if (typeof win.mostrarToast === 'function') {
        win.mostrarToast(message, variant !== 'error');
        return;
      }
      // Fallback seguro para cenários sem Bootstrap.
      var fn = variant === 'error' ? 'error' : 'info';
      if (win.console && typeof win.console[fn] === 'function') {
        win.console[fn]('[CuradoriaPreview] ' + message);
      }
    }

    function setRowDisabled(row, disabled) {
      var input = row ? row.querySelector('.input-preco-curado') : null;
      if (!row || !input) return;
      if (disabled) {
        row.classList.add('curadoria-disabled');
        row.setAttribute('title', 'Preço Booking ausente — não é possível aplicar desconto');
        input.dataset.precoCuradoSugerido = '';
        return;
      }
      row.classList.remove('curadoria-disabled');
      row.removeAttribute('title');
    }

    function hasPreviewApplied(rowEl) {
      return !!(rowEl && rowEl.dataset && rowEl.dataset.previewApplied === 'true');
    }

    function disableCumulativeApply() {
      win._curadoria_preview_aplicado = true;
    }

    function enableCumulativeApply() {
      win._curadoria_preview_aplicado = false;
    }

    function initCuradoriaRowsState() {
      getRows().forEach(function (row) {
        row.classList.add('curadoria-row');
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        var currentValue = parseCurrencyInputValue(input);
        input.dataset.originalPrecoCurado = currentValue === null ? '' : String(safeRound(currentValue));
        input.dataset.precoCuradoSugerido = '';
        input.dataset.descontoPctSugerido = '';
        input.dataset.precoExibicaoOrigem = input.dataset.precoExibicaoOrigem || row.getAttribute('data-preco-exibicao-preferida') || 'nao_disponivel';
        input.dataset.precoBaseUsado = input.dataset.precoBaseUsado || row.getAttribute('data-preco-booking') || row.getAttribute('data-preco-direto-media-periodo') || '';
        renderAuditColumnForRow(row, null);
      });
      bindAuditColumnActions();
      enableCumulativeApply();
    }

    function legacyApplyDiscount(pct) {
      var factor = 1 - (pct / 100);
      doc.querySelectorAll('.input-preco-curado').forEach(function (input) {
        var bruto = Number.parseFloat(input.getAttribute('data-bruto')) || 0;
        var valor = bruto * factor;
        input.value = formatMoneyBR(valor);
      });
    }

    function applyDiscountPreview(pct, force) {
      if (!win.FRONTEND_DESCONTO_UNIFICADO) {
        legacyApplyDiscount(pct);
        return { ok: true, legacy: true };
      }
      var pctNumber = Number(pct);
      if (!Number.isFinite(pctNumber) || pctNumber <= 0 || pctNumber > 100) {
        showPreviewToast('Insira uma porcentagem válida.', 'error');
        return { ok: false, reason: 'invalid_pct' };
      }
      if (win._curadoria_preview_aplicado && !force) {
        showPreviewToast("Preview já aplicado. Clique em 'Reset' antes de aplicar novo desconto.", 'error');
        return { ok: false, reason: 'preview_already_applied' };
      }

      var rows = getRows();
      var updated = 0;
      var skippedNoBooking = 0;
      var sampleCheckins = [];

      rows.forEach(function (row) {
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        var bruto = parsePrecoBooking(row);
        if (bruto === null) {
          setRowDisabled(row, true);
          skippedNoBooking += 1;
          return;
        }
        setRowDisabled(row, false);
        if (hasPreviewApplied(row) && !force) return;
        var previewNumber = safeRound(bruto * (1 - (pctNumber / 100)));
        input.value = formatMoneyBR(previewNumber);
        input.dataset.precoCuradoSugerido = String(previewNumber);
        input.dataset.descontoPctSugerido = String(pctNumber);
        row.dataset.previewApplied = 'true';
        updated += 1;
        if (sampleCheckins.length < 10) {
          sampleCheckins.push(row.getAttribute('data-checkin') || '');
        }
      });

      disableCumulativeApply();
      showPreviewToast('Preview calculado a partir de Preço Booking. Ao salvar, o backend revalidará.', 'success');
      logFrontendPreviewApplied(pctNumber, sampleCheckins);
      return { ok: true, updated: updated, skippedNoBooking: skippedNoBooking };
    }

    function resetDiscountPreview() {
      getRows().forEach(function (row) {
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        var original = input.dataset.originalPrecoCurado || '';
        input.value = original ? formatMoneyBR(Number(original)) : '';
        delete input.dataset.precoCuradoSugerido;
        delete input.dataset.descontoPctSugerido;
        delete row.dataset.previewApplied;
        setRowDisabled(row, false);
      });
      enableCumulativeApply();
      return { ok: true };
    }

    function prepareCuradoriaPayload() {
      var payload = [];
      getRows().forEach(function (row) {
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        var suggestedRaw = input.dataset.precoCuradoSugerido;
        if (!suggestedRaw) return;
        var precoCuradoSugerido = Number(suggestedRaw);
        if (!Number.isFinite(precoCuradoSugerido)) return;
        var precoBookingBase = parsePrecoBooking(row);
        if (precoBookingBase === null) return;
        var pctRaw = input.dataset.descontoPctSugerido;
        var descontoPctSugerido = Number(pctRaw);
        if (!Number.isFinite(descontoPctSugerido)) descontoPctSugerido = null;
        var precoExibicaoOrigem = input.dataset.precoExibicaoOrigem || row.getAttribute('data-preco-exibicao-preferida') || 'nao_disponivel';
        var precoBaseUsadoRaw = input.dataset.precoBaseUsado || row.getAttribute('data-preco-booking') || row.getAttribute('data-preco-direto-media-periodo') || '';
        var precoBaseUsado = Number(precoBaseUsadoRaw);
        if (!Number.isFinite(precoBaseUsado)) {
          precoBaseUsado = precoBookingBase;
        }

        var checkinsAttr = row.getAttribute('data-checkins') || row.getAttribute('data-checkin') || '';
        checkinsAttr.split(',').map(function (c) { return c.trim(); }).filter(Boolean).forEach(function (checkin) {
          payload.push({
            checkin: checkin,
            preco_booking_base: precoBookingBase,
            preco_curado_sugerido: precoCuradoSugerido,
            desconto_pct_sugerido: descontoPctSugerido,
            preco_exibicao_origem: precoExibicaoOrigem,
            preco_base_usado: precoBaseUsado
          });
        });
      });
      return payload;
    }

    function logFrontendEvent(action, extra) {
      var evt = {
        action: action,
        id_projeto: win.CURADORIA_PROJECT_ID || null,
        ts: new Date().toISOString()
      };
      if (extra && typeof extra === 'object') {
        Object.keys(extra).forEach(function (k) { evt[k] = extra[k]; });
      }
      try {
        if (win.navigator && typeof win.navigator.sendBeacon === 'function') {
          var blob = new Blob([JSON.stringify(evt)], { type: 'application/json' });
          win.navigator.sendBeacon('/api/system-events/frontend', blob);
          return;
        }
      } catch (e) {
        // segue para fallback
      }
      try {
        if (typeof win.fetch === 'function') {
          win.fetch('/api/system-events/frontend', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(evt),
            keepalive: true
          }).catch(function () { /* fire-and-forget */ });
          return;
        }
      } catch (err) {
        // fallback no console
      }
      if (win.console && typeof win.console.info === 'function') {
        win.console.info('[frontend_event]', evt);
      }
    }

    function renderCorrecoesModal(itensCorrigidos) {
      var tbody = doc.getElementById('tbody-correcoes-curadoria');
      if (!tbody) return;
      tbody.innerHTML = '';
      (itensCorrigidos || []).forEach(function (it) {
        var tr = doc.createElement('tr');
        tr.innerHTML = '<td>' + (it.checkin || '—') + '</td>' +
          '<td>' + formatMoneyBR(it.preco_sugerido || 0) + '</td>' +
          '<td>' + formatMoneyBR(it.preco_backend || 0) + '</td>' +
          '<td>' + (it.desconto_aplicado || '—') + '</td>';
        tbody.appendChild(tr);
      });
      var modalEl = doc.getElementById('modal-correcoes-curadoria');
      if (!modalEl) return;
      if (win.bootstrap && win.bootstrap.Modal) {
        win.bootstrap.Modal.getOrCreateInstance(modalEl).show();
      }
    }

    function openCorrectionsModal(itensCorrigidos) {
      renderCorrecoesModal(itensCorrigidos || []);
      logFrontendEvent('ui_audit_inspect_opened', {
        total_corrigidos: (itensCorrigidos || []).length
      });
    }

    function showSaveSummaryToast(respSummary) {
      var container = doc.getElementById('iva-toast-container');
      if (!container) {
        showPreviewToast(
          (respSummary.salvos || 0) + ' itens salvos, ' + (respSummary.corrigidos || 0) + ' corrigidos.',
          'success'
        );
        return;
      }
      var toastId = 'iva-save-toast-' + Date.now();
      var btnId = 'btn-ver-correcoes-' + Date.now();
      var html = '<div id="' + toastId + '" class="toast show" role="status" aria-live="polite" aria-atomic="true">' +
        '<div class="toast-header">' +
        '<strong class="me-auto">Resumo do save</strong>' +
        '<button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Fechar"></button>' +
        '</div>' +
        '<div class="toast-body">' +
        '<div>' + (respSummary.salvos || 0) + ' itens salvos, ' + (respSummary.corrigidos || 0) + ' corrigidos.</div>' +
        '<button type="button" class="btn btn-link btn-sm p-0 mt-1" id="' + btnId + '" aria-label="Ver correções aplicadas no save">Ver correções</button>' +
        '</div>' +
        '</div>';
      container.insertAdjacentHTML('beforeend', html);
      var btn = doc.getElementById(btnId);
      if (!btn) return;
      var onOpen = function () {
        logFrontendEvent('ui_ver_correcoes_clicked', {
          total_corrigidos: respSummary.corrigidos || 0
        });
        openCorrectionsModal(respSummary.itensCorrigidos || []);
      };
      btn.addEventListener('click', onOpen);
      btn.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          onOpen();
        }
      });
    }

    function renderAuditColumnForRow(rowEl, auditMeta) {
      if (!rowEl) return;
      var cell = rowEl.querySelector('.iva-curadoria-audit-col');
      if (!cell) return;
      var btn = cell.querySelector('.iva-audit-btn');
      var label = cell.querySelector('.iva-audit-label');
      if (!btn || !label) return;
      if (!auditMeta || typeof auditMeta !== 'object') {
        label.textContent = '—';
        btn.setAttribute('title', 'Sem auditoria');
        rowEl.dataset.auditRendered = 'true';
        return;
      }
      var val = auditMeta.preco_curado_salvo;
      label.textContent = (typeof val === 'number') ? String(Math.round(val)) : 'audit';
      rowEl.dataset.auditUser = auditMeta.saved_by || 'cursor-job';
      rowEl.dataset.auditTime = auditMeta.timestamp || new Date().toISOString();
      rowEl.dataset.descontoAplicado = auditMeta.desconto_aplicado || '';
      rowEl.dataset.auditRendered = 'true';
      btn.setAttribute('title', 'Audit: ' + rowEl.dataset.auditUser + ' em ' + rowEl.dataset.auditTime);
    }

    function bindAuditColumnActions() {
      if (!doc || typeof doc.addEventListener !== 'function') return;
      doc.addEventListener('click', function (ev) {
        var target = ev.target;
        var btn = target && target.closest ? target.closest('.iva-audit-btn') : null;
        if (!btn) return;
        var row = btn.closest ? btn.closest('tr[data-checkin]') : null;
        if (!row) return;
        openCorrectionsModal([{
          checkin: row.getAttribute('data-checkin') || '',
          preco_sugerido: Number((row.querySelector('.input-preco-curado') || {}).dataset.precoCuradoSugerido || 0),
          preco_backend: Number((row.querySelector('.input-preco-curado') || {}).value ? parseCurrencyInputValue(row.querySelector('.input-preco-curado')) : 0),
          desconto_aplicado: row.dataset.descontoAplicado || '—'
        }]);
      });
    }

    function handleSaveResponse(respJson, payloadSent) {
      var data = (respJson && respJson.data) ? respJson.data : {};
      var itensCorrigidos = Array.isArray(data.itens_corrigidos) ? data.itens_corrigidos : [];
      var itensInvalidos = Array.isArray(data.itens_invalidos) ? data.itens_invalidos : [];
      var salvos = Number(data.registros_salvos || 0);
      var payloadMap = {};
      (payloadSent || []).forEach(function (p) { payloadMap[p.checkin] = p; });

      // aplica valores canônicos na UI.
      Object.keys(payloadMap).forEach(function (checkin) {
        var row = getRowByCheckin(checkin);
        if (!row) return;
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        input.value = formatMoneyBR(payloadMap[checkin].preco_curado_sugerido || 0);
        row.dataset.displaySourceAfterSave = payloadMap[checkin].preco_exibicao_origem || row.getAttribute('data-preco-exibicao-preferida') || 'nao_disponivel';
        row.classList.remove('curadoria-corrigida');
        row.classList.remove('iva-curadoria-corrigida');
      });
      itensCorrigidos.forEach(function (item) {
        var row = getRowByCheckin(item.checkin);
        if (!row) return;
        var input = row.querySelector('.input-preco-curado');
        if (!input) return;
        input.value = formatMoneyBR(item.preco_backend || 0);
        row.classList.add('curadoria-corrigida');
        row.classList.add('iva-curadoria-corrigida');
        row.dataset.auditUser = 'cursor-job';
        row.dataset.auditTime = new Date().toISOString();
        row.dataset.descontoAplicado = item.desconto_aplicado || '';
        row.dataset.displaySourceAfterSave = (payloadMap[item.checkin] && payloadMap[item.checkin].preco_exibicao_origem) || row.getAttribute('data-preco-exibicao-preferida') || 'nao_disponivel';
        row.setAttribute('title', 'Linha corrigida pelo backend (valor canônico aplicado)');
        renderAuditColumnForRow(row, {
          saved_by: row.dataset.auditUser,
          timestamp: row.dataset.auditTime,
          desconto_aplicado: row.dataset.descontoAplicado,
          preco_curado_salvo: Number(item.preco_backend || 0)
        });
      });

      getRows().forEach(function (row) {
        if (!row.dataset.auditRendered) renderAuditColumnForRow(row, null);
      });

      if (itensInvalidos.length > 0) {
        showPreviewToast(salvos + ' itens salvos, ' + itensInvalidos.length + ' inválidos.', 'error');
      }
      showSaveSummaryToast({
        salvos: salvos,
        corrigidos: itensCorrigidos.length,
        invalidos: itensInvalidos.length,
        itensCorrigidos: itensCorrigidos
      });
      logFrontendEvent('curadoria_save_response_received', {
        registros_salvos: salvos,
        itens_corrigidos: itensCorrigidos.length,
        itens_invalidos: itensInvalidos.length
      });
      return { salvos: salvos, corrigidos: itensCorrigidos.length, invalidos: itensInvalidos.length };
    }

    function setSaveButtonBusy(isBusy) {
      var btn = doc.getElementById('btn-salvar-ajustes');
      if (!btn) return;
      if (!btn.dataset.originalText) btn.dataset.originalText = btn.textContent || 'Salvar Ajustes';
      if (isBusy) {
        btn.disabled = true;
        btn.textContent = 'Salvando...';
      } else {
        btn.disabled = false;
        btn.textContent = btn.dataset.originalText;
      }
    }

    function sendCuradoriaSave() {
      var payload = prepareCuradoriaPayload();
      if (!payload || payload.length === 0) {
        showPreviewToast('Nada para salvar.', 'error');
        return Promise.resolve({ ok: false, reason: 'empty_payload' });
      }
      setSaveButtonBusy(true);
      logFrontendEvent('curadoria_save_request_sent', {
        total_registros: payload.length
      });
      var controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
      var timeoutId = null;
      if (controller) {
        timeoutId = win.setTimeout(function () {
          controller.abort();
        }, 20000);
      }
      var fetchImpl = typeof win.fetch === 'function' ? win.fetch.bind(win) : null;
      if (!fetchImpl) {
        setSaveButtonBusy(false);
        showPreviewToast('Fetch indisponível no navegador atual.', 'error');
        return Promise.resolve({ ok: false, reason: 'fetch_missing' });
      }
      return fetchImpl('/api/projeto/' + encodeURIComponent(win.CURADORIA_PROJECT_ID || '') + '/curadoria', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ registros: payload }),
        signal: controller ? controller.signal : undefined
      })
        .then(function (r) {
          return r.json().then(function (json) {
            return { ok: r.ok, status: r.status, json: json };
          });
        })
        .then(function (result) {
          if (!result.ok || !result.json || !result.json.success) {
            showPreviewToast((result.json && result.json.message) || 'Erro ao salvar ajustes.', 'error');
            return { ok: false, reason: 'api_error', response: result.json };
          }
          var summary = handleSaveResponse(result.json, payload);
          // Guardrail operacional: mais de 10% corrigidos indica desvio relevante.
          if (summary.salvos > 0 && (summary.corrigidos / summary.salvos) > 0.10) {
            showPreviewToast('Atenção: mais de 10% dos itens foram corrigidos pelo backend.', 'error');
          }
          return { ok: true, response: result.json, summary: summary };
        })
        .catch(function (err) {
          showPreviewToast('Erro de rede ao salvar. Tente novamente.', 'error');
          return { ok: false, reason: 'network_error', error: String(err && err.message ? err.message : err) };
        })
        .finally(function () {
          if (timeoutId) win.clearTimeout(timeoutId);
          setSaveButtonBusy(false);
        });
    }

    function acceptCorrection(checkin) {
      var row = getRowByCheckin(checkin);
      if (!row) return false;
      row.classList.remove('curadoria-corrigida');
      return true;
    }

    function revertToSuggested(checkin) {
      var row = getRowByCheckin(checkin);
      if (!row) return false;
      var input = row.querySelector('.input-preco-curado');
      if (!input) return false;
      var suggested = input.dataset.precoCuradoSugerido;
      if (!suggested) return false;
      input.value = formatMoneyBR(Number(suggested));
      row.classList.remove('curadoria-corrigida');
      return true;
    }

    function logFrontendPreviewApplied(pct, sampleCheckins) {
      logFrontendEvent('frontend_preview_aplicado', {
        pct: pct,
        sample_checkins: sampleCheckins || []
      });
    }

    return {
      initCuradoriaRowsState: initCuradoriaRowsState,
      applyDiscountPreview: applyDiscountPreview,
      resetDiscountPreview: resetDiscountPreview,
      prepareCuradoriaPayload: prepareCuradoriaPayload,
      sendCuradoriaSave: sendCuradoriaSave,
      handleSaveResponse: handleSaveResponse,
      showSaveSummaryToast: showSaveSummaryToast,
      openCorrectionsModal: openCorrectionsModal,
      renderAuditColumnForRow: renderAuditColumnForRow,
      acceptCorrection: acceptCorrection,
      revertToSuggested: revertToSuggested,
      disableCumulativeApply: disableCumulativeApply,
      enableCumulativeApply: enableCumulativeApply,
      hasPreviewApplied: hasPreviewApplied,
      showPreviewToast: showPreviewToast
    };
  }

  var api = {
    createCuradoriaController: createCuradoriaController
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
  globalScope.CuradoriaPage = api;
})(typeof window !== 'undefined' ? window : globalThis);
