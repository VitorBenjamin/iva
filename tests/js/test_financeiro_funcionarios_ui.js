const assert = require('node:assert/strict');

function roundTo(value, decimals = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Number(n.toFixed(decimals));
}

function calcularFolhaTotalFuncionarios(funcionarios, globais = {}) {
  if (!Array.isArray(funcionarios)) return 0;
  let encargosPadrao = Number(globais.encargos_padrao || 0);
  if (encargosPadrao > 1) encargosPadrao = encargosPadrao / 100;
  const beneficioGlobal = Number(globais.vale_transporte || 0) + Number(globais.vale_alimentacao || 0);
  return roundTo(funcionarios.reduce((acc, f) => {
    const qtd = Math.max(1, Number(f.quantidade || 1));
    const salario = Number(f.salario_base || 0);
    const usarPadrao = f.usar_encargos_padrao !== false;
    let encargos = usarPadrao ? encargosPadrao : Number(f.encargos_pct || 0);
    if (encargos > 1) encargos = encargos / 100;
    const beneficios = Number(f.beneficios || 0);
    return acc + ((salario * qtd) * (1 + encargos) + beneficios + (beneficioGlobal * qtd));
  }, 0), 2);
}

function run() {
  const total = calcularFolhaTotalFuncionarios([
    { cargo: 'Recepção', quantidade: 2, salario_base: 2000, usar_encargos_padrao: true, beneficios: 300 },
    { cargo: 'Limpeza', quantidade: 1, salario_base: 1500, usar_encargos_padrao: false, encargos_pct: 20, beneficios: 100 },
  ], {
    encargos_padrao: 0.1,
    vale_transporte: 50,
    vale_alimentacao: 50,
  });
  assert.equal(total, 6900);
  console.log('OK: test_financeiro_funcionarios_ui.js');
}

run();
