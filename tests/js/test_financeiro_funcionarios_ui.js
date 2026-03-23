const assert = require('node:assert/strict');

function roundTo(value, decimals = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Number(n.toFixed(decimals));
}

function calcularFolhaTotalFuncionarios(funcionarios) {
  if (!Array.isArray(funcionarios)) return 0;
  return roundTo(funcionarios.reduce((acc, f) => {
    const qtd = Math.max(1, Number(f.quantidade || 1));
    const salario = Number(f.salario_base || 0);
    let encargos = Number(f.encargos_pct || 0);
    if (encargos > 1) encargos = encargos / 100;
    const beneficios = Number(f.beneficios || 0);
    return acc + ((salario * qtd) * (1 + encargos) + beneficios);
  }, 0), 2);
}

function run() {
  const total = calcularFolhaTotalFuncionarios([
    { cargo: 'Recepção', quantidade: 2, salario_base: 2000, encargos_pct: 0.1, beneficios: 300 },
    { cargo: 'Limpeza', quantidade: 1, salario_base: 1500, encargos_pct: 20, beneficios: 100 },
  ]);
  assert.equal(total, 6600);
  console.log('OK: test_financeiro_funcionarios_ui.js');
}

run();
