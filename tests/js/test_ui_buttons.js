const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

function run() {
  const htmlPath = path.resolve(__dirname, '../../templates/index.html');
  const jsPath = path.resolve(__dirname, '../../static/js/main.js');

  const html = fs.readFileSync(htmlPath, 'utf8');
  const js = fs.readFileSync(jsPath, 'utf8');

  assert.ok(html.includes('id="btn-criar-pousada"'));
  assert.ok(html.includes('id="btn-salvar-ativo"'));
  assert.ok(html.includes('Salvar Ativo'));
  assert.ok(html.includes('id="btn-limpar-form"'));
  assert.ok(!html.includes('id="btn-submit-ativo"'));
  assert.ok(!html.includes('id="btn-novo-ativo"'));

  assert.ok(js.includes("localStorage.getItem('ui_consolidation') === 'on'"));
  assert.ok(js.includes("document.getElementById('btn-salvar-ativo')"));
  assert.ok(js.includes("document.getElementById('btn-limpar-form')"));

  console.log('OK: test_ui_buttons.js');
}

run();
