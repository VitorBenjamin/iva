/**
 * IVA - Lógica da página principal.
 * Campos .moeda com formatação pt-BR nativa (Intl + listener); fetch /api/projetos; POST /projeto; toasts Bootstrap 5.
 */

(function () {
  'use strict';

  let projetos = [];

  function formatarMoedaBR(valor) {
    var n = Number(valor);
    if (isNaN(n) || n < 0) return 'R$ 0,00';
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(n);
  }

  function aplicarMascaraMoeda() {
    document.querySelectorAll('.moeda').forEach(function (input) {
      input.addEventListener('input', function (e) {
        var value = e.target.value.replace(/\D/g, '');
        if (value === '') {
          e.target.value = '';
          return;
        }
        value = (parseFloat(value) / 100).toFixed(2) + '';
        value = value.replace('.', ',');
        value = value.replace(/(\d)(?=(\d{3})+(?!\d))/g, '$1.');
        e.target.value = 'R$ ' + value;
      });
    });
  }

  function valorMoeda(el) {
    if (!el) return 0;
    var v = el.value.replace(/\D/g, '');
    return parseFloat(v) / 100 || 0;
  }

  function definirMoeda(el, valor) {
    if (!el) return;
    el.value = formatarMoedaBR(valor);
  }

  function coletarFinanceiroDoForm() {
    var el = function (id) { return document.getElementById(id); };
    var cf = {
      luz: valorMoeda(el('fin-luz')) || 0,
      agua: valorMoeda(el('fin-agua')) || 0,
      internet: valorMoeda(el('fin-internet')) || 0,
      iptu: valorMoeda(el('fin-iptu')) || 0,
      contabilidade: valorMoeda(el('fin-contabilidade')) || 0,
      seguros: valorMoeda(el('fin-seguros')) || 0,
      outros: valorMoeda(el('fin-outros-fixos')) || 0,
      aluguel: valorMoeda(el('fin-aluguel')) || 0
    };
    var cv = {
      cafe_manha: valorMoeda(el('fin-cafe')) || 0,
      amenities: valorMoeda(el('fin-amenities')) || 0,
      lavanderia: valorMoeda(el('fin-lavanderia')) || 0,
      outros: valorMoeda(el('fin-outros-var')) || 0
    };
    var aliquota = parseFloat(el('fin-aliquota').value) || 0;
    var contingencia = parseFloat(el('fin-contingencia').value) || 0;
    var outrosImpostos = parseFloat(el('fin-outros-impostos').value) || 0;
    if (aliquota > 1) aliquota = aliquota / 100;
    if (contingencia > 1) contingencia = contingencia / 100;
    if (outrosImpostos > 1) outrosImpostos = outrosImpostos / 100;
    return {
      custos_fixos: cf,
      folha_pagamento_mensal: valorMoeda(el('fin-folha')) || 0,
      funcionarios: [],
      custos_variaveis: cv,
      aliquota_impostos: aliquota,
      percentual_contingencia: contingencia,
      outros_impostos_taxas_percentual: outrosImpostos
    };
  }

  function mostrarToast(mensagem, sucesso) {
    var container = document.getElementById('toast-container');
    var id = 'toast-' + Date.now();
    var bg = sucesso ? 'bg-success' : 'bg-danger';
    var html = '<div id="' + id + '" class="toast align-items-center text-white ' + bg + ' border-0" role="alert">' +
      '<div class="d-flex"><div class="toast-body">' + mensagem + '</div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div></div>';
    container.insertAdjacentHTML('beforeend', html);
    var toastEl = document.getElementById(id);
    var t = new bootstrap.Toast(toastEl);
    t.show();
    toastEl.addEventListener('hidden.bs.toast', function () {
      toastEl.remove();
    });
  }

  function buscarProjetos() {
    return fetch('/api/projetos')
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.success && Array.isArray(res.data)) {
          projetos = res.data;
          return projetos;
        }
        return [];
      });
  }

  function popularDropdown() {
    var sel = document.getElementById('seletor-projeto');
    sel.innerHTML = '<option value="">— Selecionar projeto —</option>';
    projetos.forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.nome;
      sel.appendChild(opt);
    });
  }

  function preencherFormulario(projeto) {
    document.getElementById('criar-nome').value = projeto.nome || '';
    document.getElementById('criar-url').value = projeto.url_booking || '';
    document.getElementById('criar-quartos').value = projeto.numero_quartos || 1;
    definirMoeda(document.getElementById('criar-faturamento'), projeto.faturamento_anual);
    document.getElementById('criar-ano').value = projeto.ano_referencia || new Date().getFullYear();

    var fin = projeto.financeiro;
    if (fin && fin.custos_fixos) {
      var cf = fin.custos_fixos;
      definirMoeda(document.getElementById('fin-luz'), cf.luz);
      definirMoeda(document.getElementById('fin-agua'), cf.agua);
      definirMoeda(document.getElementById('fin-internet'), cf.internet);
      definirMoeda(document.getElementById('fin-iptu'), cf.iptu);
      definirMoeda(document.getElementById('fin-contabilidade'), cf.contabilidade);
      definirMoeda(document.getElementById('fin-seguros'), cf.seguros);
      definirMoeda(document.getElementById('fin-outros-fixos'), cf.outros);
      definirMoeda(document.getElementById('fin-aluguel'), cf.aluguel != null ? cf.aluguel : 0);
    } else {
      definirMoeda(document.getElementById('fin-aluguel'), 0);
    }
    definirMoeda(document.getElementById('fin-folha'), (fin && fin.folha_pagamento_mensal != null) ? fin.folha_pagamento_mensal : 0);
    if (fin && fin.custos_variaveis) {
      var cv = fin.custos_variaveis;
      definirMoeda(document.getElementById('fin-cafe'), cv.cafe_manha);
      definirMoeda(document.getElementById('fin-amenities'), cv.amenities);
      definirMoeda(document.getElementById('fin-lavanderia'), cv.lavanderia);
      definirMoeda(document.getElementById('fin-outros-var'), cv.outros);
    }
    if (fin) {
      var aliquotaVal = fin.aliquota_impostos != null ? fin.aliquota_impostos : '';
      var contingenciaVal = fin.percentual_contingencia != null ? fin.percentual_contingencia : '';
      var outrosVal = fin.outros_impostos_taxas_percentual != null ? fin.outros_impostos_taxas_percentual : '';
      document.getElementById('fin-aliquota').value = (typeof aliquotaVal === 'number' && aliquotaVal <= 1) ? (aliquotaVal * 100) : aliquotaVal;
      document.getElementById('fin-contingencia').value = (typeof contingenciaVal === 'number' && contingenciaVal <= 1) ? (contingenciaVal * 100) : contingenciaVal;
      document.getElementById('fin-outros-impostos').value = (typeof outrosVal === 'number' && outrosVal <= 1) ? (outrosVal * 100) : outrosVal;
    } else {
      document.getElementById('fin-outros-impostos').value = '';
    }

    document.getElementById('financeiro-dica').classList.add('d-none');
    document.getElementById('painel-financeiro').classList.remove('d-none');
    var linkCuradoria = document.getElementById('link-curadoria');
    if (linkCuradoria) {
      linkCuradoria.href = '/projeto/' + encodeURIComponent(projeto.id) + '/curadoria';
      linkCuradoria.style.display = '';
    }
    var btnSubmit = document.getElementById('btn-submit-ativo');
    if (btnSubmit) btnSubmit.textContent = 'Atualizar Ativo';
    var btnSalvarFin = document.getElementById('btn-salvar-financeiro');
    if (btnSalvarFin) { btnSalvarFin.style.display = ''; }
  }

  function limparSelecao() {
    document.getElementById('financeiro-dica').classList.remove('d-none');
    document.getElementById('painel-financeiro').classList.add('d-none');
    var linkCuradoria = document.getElementById('link-curadoria');
    if (linkCuradoria) {
      linkCuradoria.href = '#';
      linkCuradoria.style.display = 'none';
    }
    var btnSubmit = document.getElementById('btn-submit-ativo');
    if (btnSubmit) btnSubmit.textContent = 'Criar Ativo';
    var btnSalvarFin = document.getElementById('btn-salvar-financeiro');
    if (btnSalvarFin) { btnSalvarFin.style.display = 'none'; }
  }

  function limparFormularioCompleto() {
    document.getElementById('criar-nome').value = '';
    document.getElementById('criar-url').value = '';
    document.getElementById('criar-quartos').value = '1';
    definirMoeda(document.getElementById('criar-faturamento'), 0);
    document.getElementById('criar-ano').value = new Date().getFullYear();
    definirMoeda(document.getElementById('fin-luz'), 0);
    definirMoeda(document.getElementById('fin-agua'), 0);
    definirMoeda(document.getElementById('fin-internet'), 0);
    definirMoeda(document.getElementById('fin-iptu'), 0);
    definirMoeda(document.getElementById('fin-contabilidade'), 0);
    definirMoeda(document.getElementById('fin-seguros'), 0);
    definirMoeda(document.getElementById('fin-outros-fixos'), 0);
    definirMoeda(document.getElementById('fin-aluguel'), 0);
    definirMoeda(document.getElementById('fin-folha'), 0);
    definirMoeda(document.getElementById('fin-cafe'), 0);
    definirMoeda(document.getElementById('fin-amenities'), 0);
    definirMoeda(document.getElementById('fin-lavanderia'), 0);
    definirMoeda(document.getElementById('fin-outros-var'), 0);
    document.getElementById('fin-aliquota').value = '';
    document.getElementById('fin-contingencia').value = '';
    document.getElementById('fin-outros-impostos').value = '';
    document.getElementById('seletor-projeto').value = '';
    limparSelecao();
    var btnSubmit = document.getElementById('btn-submit-ativo');
    if (btnSubmit) btnSubmit.textContent = 'Criar Ativo';
  }

  function enviarFormAtivo(e) {
    e.preventDefault();
    var btn = document.getElementById('btn-submit-ativo');
    var nome = document.getElementById('criar-nome').value.trim();
    if (!nome) {
      mostrarToast('Informe o nome do projeto.', false);
      return;
    }
    var id = document.getElementById('seletor-projeto').value;
    var faturamento = valorMoeda(document.getElementById('criar-faturamento'));
    var payload = {
      nome: nome,
      url_booking: document.getElementById('criar-url').value.trim(),
      numero_quartos: parseInt(document.getElementById('criar-quartos').value, 10) || 1,
      faturamento_anual: faturamento,
      ano_referencia: parseInt(document.getElementById('criar-ano').value, 10) || new Date().getFullYear(),
      financeiro: coletarFinanceiroDoForm()
    };

    btn.disabled = true;
    if (id) {
      fetch('/api/projeto/' + encodeURIComponent(id), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (result) {
          if (result.ok && result.data.success) {
            mostrarToast(result.data.message || 'Projeto atualizado.', true);
            return buscarProjetos().then(function () {
              popularDropdown();
              document.getElementById('seletor-projeto').value = id;
              var p = projetos.find(function (x) { return x.id === id; });
              if (p) preencherFormulario(p);
            });
          } else {
            mostrarToast(result.data.message || 'Erro ao atualizar projeto.', false);
          }
        })
        .catch(function () {
          mostrarToast('Erro de conexão ao atualizar projeto.', false);
        })
        .finally(function () { btn.disabled = false; });
    } else {
      fetch('/projeto', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      })
        .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
        .then(function (result) {
          if (result.ok && result.data.success) {
            mostrarToast(result.data.message || 'Projeto criado.', true);
            var novoId = result.data.data && result.data.data.id;
            return buscarProjetos().then(function () {
              popularDropdown();
              if (novoId) {
                document.getElementById('seletor-projeto').value = novoId;
                var p = projetos.find(function (x) { return x.id === novoId; });
                if (p) preencherFormulario(p);
              }
            });
          } else {
            mostrarToast(result.data.message || 'Erro ao criar projeto.', false);
          }
        })
        .catch(function () {
          mostrarToast('Erro de conexão ao criar projeto.', false);
        })
        .finally(function () { btn.disabled = false; });
    }
  }

  function salvarConfiguracoesFinanceiras() {
    var id = document.getElementById('seletor-projeto').value;
    if (!id) {
      mostrarToast('Selecione um projeto para salvar as configurações financeiras.', false);
      return;
    }
    var btn = document.getElementById('btn-salvar-financeiro');
    if (btn) btn.disabled = true;
    var payload = { financeiro: coletarFinanceiroDoForm() };
    fetch('/api/projeto/' + encodeURIComponent(id), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        if (result.ok && result.data.success) {
          mostrarToast('Configurações financeiras salvas.', true);
          buscarProjetos().then(function () {
            popularDropdown();
            document.getElementById('seletor-projeto').value = id;
            var p = projetos.find(function (x) { return x.id === id; });
            if (p) preencherFormulario(p);
          });
        } else {
          mostrarToast(result.data.message || 'Erro ao salvar configurações.', false);
        }
      })
      .catch(function () {
        mostrarToast('Erro de conexão.', false);
      })
      .finally(function () {
        if (btn) btn.disabled = false;
      });
  }

  function init() {
    aplicarMascaraMoeda();
    document.getElementById('criar-ano').value = new Date().getFullYear();

    [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]')).forEach(function (el) {
      new bootstrap.Tooltip(el);
    });

    buscarProjetos().then(popularDropdown);

    document.getElementById('seletor-projeto').addEventListener('change', function () {
      var id = this.value;
      if (!id) {
        limparSelecao();
        return;
      }
      var p = projetos.find(function (x) { return x.id === id; });
      if (p) {
        preencherFormulario(p);
      } else {
        limparSelecao();
      }
    });

    document.getElementById('form-criar-projeto').addEventListener('submit', enviarFormAtivo);

    var btnNovo = document.getElementById('btn-novo-ativo');
    if (btnNovo) btnNovo.addEventListener('click', limparFormularioCompleto);

    var btnSalvarFin = document.getElementById('btn-salvar-financeiro');
    if (btnSalvarFin) btnSalvarFin.addEventListener('click', salvarConfiguracoesFinanceiras);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
