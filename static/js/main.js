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

  function coletarInfraestruturaDoForm() {
    var el = function (id) { return document.getElementById(id); };
    var v = function (id) {
      var e = el(id);
      return (e && e.value && e.value.trim()) ? e.value.trim() : null;
    };
    return {
      tipo_unidade: v('infra-tipo-unidade'),
      matriz_energetica: v('infra-matriz-energetica'),
      matriz_hidrica: v('infra-matriz-hidrica'),
      modelo_lavanderia: v('infra-modelo-lavanderia')
    };
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
    var mediaPessoas = parseFloat(el('fin-media-pessoas').value) || 2;
    if (aliquota > 1) aliquota = aliquota / 100;
    if (contingencia > 1) contingencia = contingencia / 100;
    if (outrosImpostos > 1) outrosImpostos = outrosImpostos / 100;
    mediaPessoas = Math.max(0.1, Math.min(10, mediaPessoas));
    return {
      custos_fixos: cf,
      folha_pagamento_mensal: valorMoeda(el('fin-folha')) || 0,
      funcionarios: [],
      custos_variaveis: cv,
      media_pessoas_por_diaria: mediaPessoas,
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
    sel.innerHTML = '<option value="">— Selecionar pousada —</option>';
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

    var inf = projeto.infraestrutura;
    var selIds = ['infra-tipo-unidade', 'infra-matriz-energetica', 'infra-matriz-hidrica', 'infra-modelo-lavanderia'];
    var dimMap = { 'infra-tipo-unidade': 'tipo_unidade', 'infra-matriz-energetica': 'matriz_energetica', 'infra-matriz-hidrica': 'matriz_hidrica', 'infra-modelo-lavanderia': 'modelo_lavanderia' };
    if (inf) {
      selIds.forEach(function (id) {
        var key = dimMap[id];
        var val = (inf[key] && inf[key].trim()) ? inf[key] : '';
        var e = document.getElementById(id);
        if (e) e.value = val;
        var btn = document.querySelector('.infra-btn[data-infra="' + key + '"][data-value="' + val + '"]');
        document.querySelectorAll('.infra-btn[data-infra="' + key + '"]').forEach(function (b) {
          b.classList.remove('active', 'btn-primary');
          b.classList.add('btn-outline-primary');
        });
        if (btn && val) {
          btn.classList.add('active', 'btn-primary');
          btn.classList.remove('btn-outline-primary');
        }
      });
    } else {
      selIds.forEach(function (id) {
        var e = document.getElementById(id);
        if (e) e.value = '';
        var key = dimMap[id];
        document.querySelectorAll('.infra-btn[data-infra="' + key + '"]').forEach(function (b) {
          b.classList.remove('active', 'btn-primary');
          b.classList.add('btn-outline-primary');
        });
      });
    }
    document.getElementById('infraestrutura-dica').classList.add('d-none');
    document.getElementById('painel-infraestrutura').classList.remove('d-none');
    var btnCalibrar = document.getElementById('btn-calibrar');
    if (btnCalibrar) btnCalibrar.disabled = !(document.getElementById('infra-tipo-unidade').value || '').trim();

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
    var mediaPessoasEl = document.getElementById('fin-media-pessoas');
    if (mediaPessoasEl) {
      var mp = (fin && fin.media_pessoas_por_diaria != null) ? Number(fin.media_pessoas_por_diaria) : 2;
      mediaPessoasEl.value = (mp >= 0.1 && mp <= 10) ? mp : 2;
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
    document.getElementById('infraestrutura-dica').classList.remove('d-none');
    document.getElementById('painel-infraestrutura').classList.add('d-none');
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
    var finMedia = document.getElementById('fin-media-pessoas');
    if (finMedia) finMedia.value = '2';
    document.getElementById('fin-aliquota').value = '';
    document.getElementById('fin-contingencia').value = '';
    document.getElementById('fin-outros-impostos').value = '';
    document.getElementById('infra-tipo-unidade').value = '';
    document.getElementById('infra-matriz-energetica').value = '';
    document.getElementById('infra-matriz-hidrica').value = '';
    document.getElementById('infra-modelo-lavanderia').value = '';
    document.querySelectorAll('.infra-btn').forEach(function (b) {
      b.classList.remove('active', 'btn-primary');
      b.classList.add('btn-outline-primary');
    });
    var btnCalibrar = document.getElementById('btn-calibrar');
    if (btnCalibrar) btnCalibrar.disabled = true;
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
      financeiro: coletarFinanceiroDoForm(),
      infraestrutura: coletarInfraestruturaDoForm()
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

  function aplicarPresets() {
    var infra = coletarInfraestruturaDoForm();
    var numeroQuartos = parseInt(document.getElementById('criar-quartos').value, 10) || 10;
    var params = new URLSearchParams({
      tipo_unidade: infra.tipo_unidade || 'quarto_standard',
      numero_quartos: String(numeroQuartos)
    });
    if (infra.matriz_energetica) params.set('matriz_energetica', infra.matriz_energetica);
    if (infra.matriz_hidrica) params.set('matriz_hidrica', infra.matriz_hidrica);
    if (infra.modelo_lavanderia) params.set('modelo_lavanderia', infra.modelo_lavanderia);
    fetch('/api/presets-infraestrutura?' + params.toString())
      .then(function (r) { return r.json(); })
      .then(function (json) {
        if (!json.success || !json.data) {
          mostrarToast(json.message || 'Erro ao obter presets.', false);
          return;
        }
        var d = json.data;
        var cafeEl = document.getElementById('fin-cafe');
        var lavEl = document.getElementById('fin-lavanderia');
        var luzEl = document.getElementById('fin-luz');
        var aguaEl = document.getElementById('fin-agua');
        var mediaEl = document.getElementById('fin-media-pessoas');
        var temCafe = valorMoeda(cafeEl) > 0;
        var temLav = valorMoeda(lavEl) > 0;
        var temLuz = valorMoeda(luzEl) > 0;
        var temAgua = valorMoeda(aguaEl) > 0;
        var algumPreenchido = temCafe || temLav || temLuz || temAgua;
        function aplicar(substituirTudo) {
          if (mediaEl) mediaEl.value = String(d.media_pessoas_por_diaria);
          if (substituirTudo || !temCafe) definirMoeda(cafeEl, d.cafe_manha);
          if (substituirTudo || !temLav) definirMoeda(lavEl, d.lavanderia);
          if (substituirTudo || !temLuz) definirMoeda(luzEl, d.sugestao_luz);
          if (substituirTudo || !temAgua) definirMoeda(aguaEl, d.sugestao_agua);
          mostrarToast('Valores calibrados aplicados. Revise e ajuste conforme necessário.', true);
        }
        if (!algumPreenchido) {
          aplicar(true);
          return;
        }
        var modalEl = document.getElementById('modal-calibrar-confirm');
        if (!modalEl) {
          modalEl = document.createElement('div');
          modalEl.id = 'modal-calibrar-confirm';
          modalEl.className = 'modal fade';
          modalEl.setAttribute('tabindex', '-1');
          modalEl.innerHTML =
            '<div class="modal-dialog modal-dialog-centered">' +
            '  <div class="modal-content">' +
            '    <div class="modal-header"><h5 class="modal-title">Calibrar com benchmark</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>' +
            '    <div class="modal-body">Alguns campos já têm valor. Deseja substituir pelos valores calibrados ou preencher apenas os campos vazios?</div>' +
            '    <div class="modal-footer">' +
            '      <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>' +
            '      <button type="button" class="btn btn-outline-primary" id="btn-calibrar-vazios">Preencher vazios</button>' +
            '      <button type="button" class="btn btn-success" id="btn-calibrar-tudo">Substituir tudo</button>' +
            '    </div>' +
            '  </div>' +
            '</div>';
          document.body.appendChild(modalEl);
        }
        var modal = new bootstrap.Modal(modalEl);
        modal.show();
        var btnTudo = document.getElementById('btn-calibrar-tudo');
        var btnVazios = document.getElementById('btn-calibrar-vazios');
        function off() {
          if (btnTudo) btnTudo.removeEventListener('click', onTudo);
          if (btnVazios) btnVazios.removeEventListener('click', onVazios);
        }
        function onTudo() {
          off();
          modal.hide();
          aplicar(true);
        }
        function onVazios() {
          off();
          modal.hide();
          aplicar(false);
        }
        if (btnTudo) btnTudo.addEventListener('click', onTudo);
        if (btnVazios) btnVazios.addEventListener('click', onVazios);
        modalEl.addEventListener('hidden.bs.modal', function () { off(); }, { once: true });
      })
      .catch(function () {
        mostrarToast('Erro de conexão ao obter presets.', false);
      });
  }

  function renderizarChecklist(checklist, containerId) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var labels = {
      scraper_config_exists: 'Config do scraper',
      booking_url_valid: 'URL Booking válida',
      market_bruto_exists: 'Market bruto',
      permissions_ok: 'Permissões',
      backups_dir_exists: 'Pasta backups'
    };
    var html = '';
    for (var k in labels) {
      var ok = checklist[k] === true;
      var cls = ok ? 'text-success' : 'text-danger';
      var icon = ok ? 'bi-check-circle-fill' : 'bi-x-circle-fill';
      html += '<span class="' + cls + ' me-2"><i class="bi ' + icon + ' me-1"></i>' + labels[k] + '</span>';
    }
    container.innerHTML = html || '<span class="text-muted">Nenhum item</span>';
  }

  function atualizarChecklistOnboarding(id) {
    var secao = document.getElementById('secao-checklist-onboarding');
    if (!secao) return;
    if (!id) {
      secao.classList.add('d-none');
      return;
    }
    fetch('/api/pousada/' + encodeURIComponent(id) + '/validate')
      .then(function (r) { return r.json(); })
      .then(function (res) {
        secao.classList.remove('d-none');
        var checklist = (res.data && res.data.checklist) ? res.data.checklist : (res.checklist || {});
        renderizarChecklist(checklist, 'checklist-itens');
        var linkCuradoria = document.getElementById('link-checklist-curadoria');
        var linkScraper = document.getElementById('link-checklist-scraper');
        if (linkCuradoria) linkCuradoria.href = '/projeto/' + encodeURIComponent(id) + '/curadoria';
        if (linkScraper) linkScraper.href = '/projeto/' + encodeURIComponent(id) + '/curadoria#scraper';
      })
      .catch(function () {
        secao.classList.add('d-none');
      });
  }

  function enviarCriarPousada() {
    var btn = document.getElementById('btn-submit-pousada');
    var nome = (document.getElementById('pousada-nome') || {}).value.trim();
    var url = (document.getElementById('pousada-booking-url') || {}).value.trim();
    if (!nome || !url) {
      mostrarToast('Nome e URL Booking são obrigatórios.', false);
      return;
    }
    var payload = {
      nome: nome,
      booking_url: url,
      cidade: (document.getElementById('pousada-cidade') || {}).value.trim() || undefined,
      timezone: (document.getElementById('pousada-timezone') || {}).value.trim() || undefined,
      executar_scrape_imediato: (document.getElementById('pousada-executar-scrape') || {}).checked || false
    };
    btn.disabled = true;
    fetch('/api/pousada', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (data) { return { ok: r.ok, status: r.status, data: data }; }); })
      .then(function (result) {
        if (result.ok && result.data.success) {
          var d = result.data;
          document.getElementById('resultado-criar-pousada').classList.remove('d-none');
          renderizarChecklist(d.checklist || {}, 'checklist-resultado');
          var id = d.id;
          var linkCuradoria = document.getElementById('link-resultado-curadoria');
          var linkScraper = document.getElementById('link-resultado-scraper');
          if (linkCuradoria) linkCuradoria.href = '/projeto/' + encodeURIComponent(id) + '/curadoria';
          if (linkScraper) linkScraper.href = '/projeto/' + encodeURIComponent(id) + '/curadoria#scraper';
          mostrarToast('Pousada criada: ' + (d.id || nome), true);
          buscarProjetos().then(function () {
            popularDropdown();
            document.getElementById('seletor-projeto').value = id;
            var p = projetos.find(function (x) { return x.id === id; });
            if (p) preencherFormulario(p);
            atualizarChecklistOnboarding(id);
          });
        } else {
          mostrarToast(result.data.message || 'Erro ao criar pousada.', false);
        }
      })
      .catch(function () {
        mostrarToast('Erro de conexão ao criar pousada.', false);
      })
      .finally(function () { btn.disabled = false; });
  }

  function salvarConfiguracoesFinanceiras() {
    var id = document.getElementById('seletor-projeto').value;
    if (!id) {
      mostrarToast('Selecione um projeto para salvar as configurações financeiras.', false);
      return;
    }
    var btn = document.getElementById('btn-salvar-financeiro');
    if (btn) btn.disabled = true;
    var payload = {
      financeiro: coletarFinanceiroDoForm(),
      infraestrutura: coletarInfraestruturaDoForm()
    };
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
        atualizarChecklistOnboarding(null);
        return;
      }
      var p = projetos.find(function (x) { return x.id === id; });
      if (p) {
        preencherFormulario(p);
        atualizarChecklistOnboarding(id);
      } else {
        limparSelecao();
        atualizarChecklistOnboarding(null);
      }
    });

    document.getElementById('form-criar-projeto').addEventListener('submit', enviarFormAtivo);

    var tipoUnidadeEl = document.getElementById('infra-tipo-unidade');
    if (tipoUnidadeEl) {
      tipoUnidadeEl.addEventListener('change', function () {
        var mediaEl = document.getElementById('fin-media-pessoas');
        if (!mediaEl) return;
        var v = (this.value || '').trim();
        if (v === 'chale_com_cozinha') mediaEl.value = '2.46';
        else if (v === 'quarto_standard') mediaEl.value = '2.1';
        else if (v === 'apartamento') mediaEl.value = '2.2';
      });
    }

    var selectIdPorDim = { tipo_unidade: 'infra-tipo-unidade', matriz_energetica: 'infra-matriz-energetica', matriz_hidrica: 'infra-matriz-hidrica', modelo_lavanderia: 'infra-modelo-lavanderia' };
    document.querySelectorAll('.infra-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var dim = this.getAttribute('data-infra');
        var val = this.getAttribute('data-value') || '';
        var selectId = selectIdPorDim[dim];
        var sel = selectId ? document.getElementById(selectId) : null;
        document.querySelectorAll('.infra-btn[data-infra="' + dim + '"]').forEach(function (b) {
          b.classList.remove('active', 'btn-primary');
          b.classList.add('btn-outline-primary');
        });
        this.classList.add('active', 'btn-primary');
        this.classList.remove('btn-outline-primary');
        if (sel) {
          sel.value = val;
          sel.dispatchEvent(new Event('change'));
        }
        var btnCalibrar = document.getElementById('btn-calibrar');
        if (btnCalibrar) {
          var tipoVal = (document.getElementById('infra-tipo-unidade') || {}).value || '';
          btnCalibrar.disabled = !tipoVal.trim();
        }
      });
    });

    var btnCalibrar = document.getElementById('btn-calibrar');
    if (btnCalibrar) btnCalibrar.addEventListener('click', aplicarPresets);

    var btnNovo = document.getElementById('btn-novo-ativo');
    if (btnNovo) btnNovo.addEventListener('click', limparFormularioCompleto);

    var btnSalvarFin = document.getElementById('btn-salvar-financeiro');
    if (btnSalvarFin) btnSalvarFin.addEventListener('click', salvarConfiguracoesFinanceiras);

    var btnCriarPousada = document.getElementById('btn-criar-pousada');
    if (btnCriarPousada) {
      btnCriarPousada.addEventListener('click', function () {
        document.getElementById('resultado-criar-pousada').classList.add('d-none');
        var modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('modal-criar-pousada'));
        modal.show();
      });
    }
    var btnSubmitPousada = document.getElementById('btn-submit-pousada');
    if (btnSubmitPousada) btnSubmitPousada.addEventListener('click', enviarCriarPousada);

    document.getElementById('modal-criar-pousada').addEventListener('show.bs.modal', function () {
      document.getElementById('resultado-criar-pousada').classList.add('d-none');
    });

    var btnEditarConfig = document.getElementById('btn-checklist-editar-config');
    if (btnEditarConfig) {
      btnEditarConfig.addEventListener('click', function () {
        var card = document.getElementById('card-gestao-ativo');
        if (card) card.scrollIntoView({ behavior: 'smooth' });
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
