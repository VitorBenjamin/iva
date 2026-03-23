/* Teste E2E opcional (headless) para staging/local. */
const path = require('node:path');
const fs = require('node:fs');
const cp = require('node:child_process');

if (String(process.env.SKIP_BROWSER_TESTS || '').toLowerCase() === 'true') {
  console.log('SKIP: test_curadoria_preview_e2e.js (SKIP_BROWSER_TESTS=true)');
  process.exit(0);
}

let playwright;
try {
  playwright = require('playwright');
} catch (err) {
  console.log('SKIP: Playwright não instalado. Defina SKIP_BROWSER_TESTS=true no CI ou instale playwright.');
  process.exit(0);
}

async function run() {
  const root = path.resolve(__dirname, '../..');
  const screenshotDir = path.join(root, 'audits', 'screenshots');
  fs.mkdirSync(screenshotDir, { recursive: true });

  const appPath = path.join(root, 'app.py');
  const server = cp.spawn('python', [appPath], {
    cwd: root,
    stdio: 'ignore',
    env: {
      ...process.env,
      FRONTEND_DESCONTO_UNIFICADO: 'true'
    }
  });

  const baseUrl = process.env.E2E_BASE_URL || 'http://127.0.0.1:5000';
  const projectId = process.env.E2E_PROJECT_ID || 'front-back-integration-pousada';
  const url = `${baseUrl}/projeto/${encodeURIComponent(projectId)}/curadoria`;

  // aguarda o servidor subir.
  await new Promise((resolve) => setTimeout(resolve, 2500));

  const browser = await playwright.chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.fill('#input-desconto-pct', '15');
    await page.click('#btn-aplicar-desconto');
    await page.waitForTimeout(300);

    const firstValue = await page.$eval('.input-preco-curado', (el) => el.value || '');
    if (!firstValue.includes('850')) {
      throw new Error(`Preview inesperado: ${firstValue}`);
    }

    await page.screenshot({ path: path.join(screenshotDir, 'ato3_3_4_preview.png'), fullPage: true });
    console.log('OK: test_curadoria_preview_e2e.js');
  } finally {
    await browser.close();
    server.kill();
  }
}

run().catch((err) => {
  console.error(`FAIL: test_curadoria_preview_e2e.js -> ${err.message}`);
  process.exit(1);
});
