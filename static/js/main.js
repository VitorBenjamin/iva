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
    }
    if (fin && fin.custos_variaveis) {
      var cv = fin.custos_variaveis;
      definirMoeda(document.getElementById('fin-cafe'), cv.cafe_manha);
      definirMoeda(document.getElementById('fin-amenities'), cv.amenities);
      definirMoeda(document.getElementById('fin-lavanderia'), cv.lavanderia);
      definirMoeda(document.getElementById('fin-outros-var'), cv.outros);
    }
    if (fin) {
      document.getElementById('fin-aliquota').value = fin.aliquota_impostos ?? '';
      document.getElementById('fin-contingencia').value = fin.percentual_contingencia ?? '';
    }

    document.getElementById('financeiro-dica').classList.add('d-none');
    document.getElementById('painel-financeiro').classList.remove('d-none');
    var linkDash = document.getElementById('link-dashboard');
    if (linkDash) {
      linkDash.href = '/projeto/' + encodeURIComponent(projeto.id) + '/dashboard';
      linkDash.style.display = '';
    }
  }

  function limparSelecao() {
    document.getElementById('financeiro-dica').classList.remove('d-none');
    document.getElementById('painel-financeiro').classList.add('d-none');
    var linkDash = document.getElementById('link-dashboard');
    if (linkDash) {
      linkDash.href = '#';
      linkDash.style.display = 'none';
    }
  }

  function enviarCriarProjeto(e) {
    e.preventDefault();
    var btn = document.getElementById('btn-criar');
    var nome = document.getElementById('criar-nome').value.trim();
    if (!nome) {
      mostrarToast('Informe o nome do projeto.', false);
      return;
    }
    var faturamentoEl = document.getElementById('criar-faturamento');
    var faturamento = valorMoeda(faturamentoEl);
    var payload = {
      nome: nome,
      url_booking: document.getElementById('criar-url').value.trim(),
      numero_quartos: parseInt(document.getElementById('criar-quartos').value, 10) || 1,
      faturamento_anual: faturamento,
      ano_referencia: parseInt(document.getElementById('criar-ano').value, 10) || new Date().getFullYear()
    };

    btn.disabled = true;
    fetch('/projeto', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, data: data }; }); })
      .then(function (result) {
        if (result.ok && result.data.success) {
          mostrarToast(result.data.message || 'Projeto criado.', true);
          var id = result.data.data && result.data.data.id;
          return buscarProjetos().then(function () {
            popularDropdown();
            if (id) {
              document.getElementById('seletor-projeto').value = id;
              var p = projetos.find(function (x) { return x.id === id; });
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
      .finally(function () {
        btn.disabled = false;
      });
  }

  function init() {
    aplicarMascaraMoeda();
    document.getElementById('criar-ano').value = new Date().getFullYear();

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

    document.getElementById('form-criar-projeto').addEventListener('submit', enviarCriarProjeto);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
